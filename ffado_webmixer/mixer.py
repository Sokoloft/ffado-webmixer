"""The FFADO mixer: reads and writes the connected device (any FFADO device, not one model).

Channels, buses and names come from FFADO matrix mixers. XML profiles provide
source-derived device-specific metadata; missing controls stay unavailable.
"""
from .profile_loader import (load_profile, resolve_mixer, resolve_controls,
                             visible_columns, destination_options, bus_name, CHANNEL_WORDS)
from .helper import FfadoHelper
from .controls import to_percent, from_percent, pan_to_ui, pan_from_ui
from .interrogate import discover
from functools import wraps
import math


def serialized_output(method):
    """Keep output mute read/modify/write sequences atomic across API threads."""
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self.helper.transaction():
            return method(self, *args, **kwargs)
    return wrapper


def load_device_info(config=None):
    """Discover the currently connected FFADO hardware; never persist its topology.

    XML profiles describe known controls and model-specific interpretation.
    The live D-Bus tree supplies the actual available paths and matrix dimensions.
    """
    print("Interrogating connected FFADO hardware...")
    return discover()


class Mixer:
    def __init__(self, config, device_index=0):
        self.config = config
        data = load_device_info()
        self.device = data["devices"][device_index]
        self.helper = FfadoHelper()
        self.profile = self._find_profile()
        mixer = resolve_mixer(self.device, self.profile)
        if mixer is None:
            raise RuntimeError("Selected FFADO device exposes no matrix mixer")
        self.mixes, self.columns = mixer["rows"], mixer["columns"]
        self.matrix = mixer
        self.router_path = next((r["path"] for r in self.device.get("routers", [])
                                 if r["path"].endswith("/EAP/Router")), None)
        self._matrix_mutes = {}  # (bus, channel) -> original coefficient, for soft mute
        self.model = self._info(self.profile.get("model_element"))
        resolved = resolve_controls(self.device, self.profile, mixer["matrices"], self.columns, self.mixes)
        self.roles = resolved["roles"]
        self.out_spec = resolved["output_spec"]
        self.outputs = resolved["outputs"]
        self.chan = resolved["channels"]
        self.chan_specs = resolved["channel_specs"]
        self.mute_memory = config.mute_memory

    # ---------- matrix orientation and native levels ----------
    def _coordinates(self, mix, col):
        return (col, mix) if self.matrix["transposed"] else (mix, col)

    def _get_cell(self, path, mix, col):
        return self.helper.get_cell(path, *self._coordinates(mix, col))

    def _set_cell(self, path, mix, col, value):
        self.helper.set_cell(path, *self._coordinates(mix, col), value)
        if self.matrix["mode"] == "dice_db":
            actual = self.helper.get_cell(path, *self._coordinates(mix, col))
            if not math.isfinite(float(actual)) or abs(float(actual) - float(value)) > 1:
                raise IOError("FFADO did not apply mixer value; check hardware mixer state")

    def _to_ui(self, raw, spec):
        raw = float(raw)
        if spec.get("type") in ("dice_db", "rme_db"):
            if not math.isfinite(raw) or raw <= 16:
                return 0
            db = 20 * math.log10(raw / 16384.0)
            return round(max(0, min(100, (db + 60) * (100 / 66))))
        return to_percent(raw, spec.get("min", 0), spec.get("max", 1)) if math.isfinite(raw) else 0

    def _from_ui(self, ui, spec):
        if spec.get("type") in ("dice_db", "rme_db"):
            pct = max(0, min(100, float(ui)))
            return 0 if pct == 0 else round(16384 * 10 ** (((pct * 66 / 100) - 60) / 20))
        return from_percent(ui, spec.get("min", 0), spec.get("max", 1))

    # ---------- profile / discovered controls ----------
    def _find_profile(self):
        return load_profile(self.device)

    def _info(self, suffix):
        """Current value of a cached control found by path suffix, e.g. 'Info/SampleRate'."""
        control = next((c for c in self.device["controls"] if suffix and c["path"].endswith("/" + suffix)), None)
        return self.helper.get_value(control["path"], control["kind"]) if control else None

    def _visible_cols(self):
        rate = self._info(self.profile.get("rate_element"))
        return visible_columns(self.profile, self.model, self.columns, rate)

    # ---------- what the web server uses ----------
    def describe(self):
        model = self.profile.get("models", {}).get(str(self.model), {})
        fader = self.roles.get("fader", (None, {}))[1]
        features = {}
        for role in ("pan", "solo"):
            if role in self.roles:
                features[role] = {"writable": self.roles[role][1]["writable"]}
        for role in CHANNEL_WORDS:
            if any(role in c for c in self.chan.values()):
                spec = self.chan_specs[role]
                features[role] = {"writable": spec["writable"], "min": spec.get("min", 0), "max": spec.get("max", 1)}
        return {
            "device": model.get("name") or self.profile.get("device_name") or f"FFADO device {self.device['guid']}",
            "mixes": [{"id": i, "name": bus_name(n)} for i, n in enumerate(self.mixes)],
            "outputs": [{"id": o["id"], "name": o["name"], "mix": o["mix"], "controllable": o["fader"] is not None,
                         "destination": o["dest"] is not None and bool(self._dest_options())}
                        for o in self.outputs.values()],
            "fader": {"writable": fader.get("writable", False)},
            "mute": {"writable": bool(self.roles.get("mute") or self._soft_mute())},
            "matrix": {"available": "fader" in self.roles, "path": self.matrix["path"],
                       "mode": self.matrix["mode"]},
            "router": bool(self.router_path),
            "bus_routing": bool(self.profile.get("family") == "motu" and
                                self._dest_options() and
                                any(out["dest"] is not None for out in self.outputs.values())),
            "features": features,
            "controls": {role: spec for role, (_, spec) in self.roles.items()},
            "globals": [c for c in self.device["controls"] if not c["path"].endswith(("/Info/Model", "/Info/IsStreaming"))],
        }

    def _soft_mute(self):
        return self.matrix["mode"] == "dice_db" and "mute" not in self.roles

    def read_mix(self, mix):
        if not 0 <= mix < len(self.mixes):
            raise ValueError("mix out of range")
        out = {}
        for col in self._visible_cols():
            entry = {"name": self.columns[col], "input": self.columns[col]}   # "input" is the fixed hardware name
            if "fader" in self.roles:
                path, spec = self.roles["fader"]
                raw = self._get_cell(path, mix, col)
                saved = self._matrix_mutes.get((mix, col))
                if saved is not None and raw != 0:
                    del self._matrix_mutes[(mix, col)]
                    saved = None
                entry["fader"] = self._to_ui(saved if saved is not None else raw, spec) if spec["writable"] else 0
                if self._soft_mute():
                    entry["mute"] = raw == 0
            if "pan" in self.roles:
                path, spec = self.roles["pan"]
                raw = self._get_cell(path, mix, col)
                lo, hi = spec.get("min", 0), spec.get("max", 1)
                entry["pan"] = pan_to_ui(raw, lo, hi) if spec["writable"] else 0.0
            for role in ("mute", "solo"):
                if role in self.roles:
                    entry[role] = bool(self._get_cell(self.roles[role][0], mix, col))
            for role, control in self.chan.get(col, {}).items():
                value = self.helper.get_value(control["path"], control["kind"])
                entry[role] = bool(value) if role == "invert" else value
            out[f"ch/{col:02d}"] = entry      # zero-padded: JSON keys sort alphabetically
        return out

    def write(self, mix, strip, control, value):
        col = int(strip.split("/")[1])
        if not (0 <= col < len(self.columns)):
            raise ValueError("channel out of range")

        if not 0 <= mix < len(self.mixes):
            raise ValueError("mix out of range")
        if control in CHANNEL_WORDS:                      # per-channel, same in every mix
            target = self.chan.get(col, {}).get(control)
            spec = self.chan_specs[control]
            if target is None:
                raise ValueError(f"{self.columns[col]} has no {control} control")
            if not spec["writable"]:
                raise ValueError(f"{control} is read-only until a profile defines its range")
            if control == "invert":
                raw = 1 if value else 0
            else:
                raw = round(max(spec["min"], min(spec["max"], float(value))))
            self.helper.set_value(target["path"], target["kind"], raw)
            return

        if self._soft_mute() and control == "mute" and "fader" in self.roles:
            with self.helper.transaction():
                path = self.roles["fader"][0]
                old = self._get_cell(path, mix, col)
                key = (mix, col)
                if value and old > 0:
                    self._matrix_mutes[key] = old
                    self._set_cell(path, mix, col, 0)
                elif not value and old == 0:
                    restore = self._matrix_mutes.pop(key, None)
                    if restore is None:
                        raise ValueError("No saved gain for this muted crosspoint; raise its fader to restore audio")
                    self._set_cell(path, mix, col, restore)
            return
        if control not in ("fader", "pan", "mute", "solo") or control not in self.roles:
            raise ValueError(f"{control} is not controllable on this device")
        path, spec = self.roles[control]
        if not spec["writable"]:
            raise ValueError(f"{control} is read-only until a profile defines its range")
        if not 0 <= mix < len(self.mixes):
            raise ValueError("mix out of range")
        lo, hi = spec.get("min", 0), spec.get("max", 1)
        if control == "fader":
            if self._soft_mute() and (mix, col) in self._matrix_mutes:
                self._matrix_mutes[(mix, col)] = self._from_ui(value, spec)
                return
            raw = self._from_ui(value, spec)
        elif control == "pan":
            raw = pan_from_ui(value, lo, hi)
        else:
            raw = 1 if value else 0
        self._set_cell(path, mix, col, raw)


    def _read_scalar(self, control):
        if control["kind"] == "Boolean":
            return self.helper.get_selected(control["path"], "Boolean")
        return self.helper.get_value(control["path"], control["kind"])

    def _write_scalar(self, control, value):
        if control["kind"] == "Boolean":
            return self.helper.select(control["path"], bool(value), "Boolean")
        return self.helper.set_value(control["path"], control["kind"], value)

    # ---------- matrix and crossbar router API ----------
    def matrix_snapshot(self):
        if "fader" not in self.roles:
            raise ValueError("No writable gain matrix exposed for this device")
        path, spec = self.roles["fader"]
        with self.helper.transaction():
            values = [[self._to_ui(self._get_cell(path, mix, col), spec)
                       for mix in range(len(self.mixes))] for col in range(len(self.columns))]
        return {"inputs": self.columns, "outputs": self.mixes, "values": values,
                "mode": self.matrix["mode"]}

    def matrix_set(self, input_index, output_index, value):
        if "fader" not in self.roles or not self.roles["fader"][1]["writable"]:
            raise ValueError("No writable gain matrix on this device")
        if not (0 <= input_index < len(self.columns) and 0 <= output_index < len(self.mixes)):
            raise ValueError("Invalid mixer matrix coordinate")
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
            raise ValueError("Mixer gain must be between 0 and 100")
        self.write(output_index, f"ch/{input_index:02d}", "fader", value)

    def router_snapshot(self):
        if not self.router_path:
            raise ValueError("No FFADO crossbar router exposed for this device")
        path = self.router_path
        with self.helper.transaction():
            sources = [str(x) for x in self.helper.router_call(path, "getSourceNames")]
            destinations = [str(x) for x in self.helper.router_call(path, "getDestinationNames")]
            selected = {d: str(self.helper.router_call(path, "getSourceForDestination", d))
                        for d in destinations}
        return {"sources": sources, "destinations": destinations, "selected": selected}

    def router_set(self, destination, source):
        if not self.router_path:
            raise ValueError("No FFADO crossbar router exposed")
        with self.helper.transaction():
            sources = [str(x) for x in self.helper.router_call(self.router_path, "getSourceNames")]
            destinations = [str(x) for x in self.helper.router_call(self.router_path, "getDestinationNames")]
            if (source and source not in sources) or destination not in destinations:
                raise ValueError("Source or destination is not available")
            before = str(self.helper.router_call(self.router_path, "getSourceForDestination", destination))
            if before == source:
                return
            # Match FFADO's OutputSwitcher: disconnect the previous route,
            # then connect the requested source. Disconnection mutes only
            # this destination; it does not clear the whole router.
            if before:
                if not self.helper.router_call(self.router_path, "setConnectionState", before, destination, False):
                    raise ValueError("FFADO could not disconnect the previous route")
            if source:
                if not self.helper.router_call(self.router_path, "setConnectionState", source, destination, True):
                    if before:
                        self.helper.router_call(self.router_path, "setConnectionState", before, destination, True)
                    raise ValueError("FFADO rejected that routing connection")
            actual = str(self.helper.router_call(self.router_path, "getSourceForDestination", destination))
            if actual != source:
                raise IOError("FFADO routing readback did not match the requested connection")

    # ---------- source-defined MOTU mix-bus destination routing ----------
    def bus_routing_snapshot(self):
        """Output-assignment matrix; unlike matrix_snapshot this NEVER reads gain.

        On pre-mk3 MOTU hardware each Mix_dest scalar selects one destination
        for that bus. Other buses may use the same destination. There is no
        general per-output crossbar exposed on this hardware.
        """
        if self.profile.get("family") != "motu":
            raise ValueError("This device uses a different routing interface")
        options = self._dest_options()
        if not options:
            raise ValueError("No device-specific routing destinations are known")
        buses = []
        with self.helper.transaction():
            for out in self.outputs.values():
                if out["mix"] is None or out["dest"] is None:
                    continue
                value = int(self.helper.get_value(out["dest"]["path"], out["dest"]["kind"]))
                buses.append({"id": out["id"], "name": out["name"], "value": value})
        if not buses:
            raise ValueError("No bus destination controls reported by FFADO")
        return {"buses": buses, "destinations": options, "kind": "motu_mix_dest"}

    def bus_routing_set(self, bus_id, value):
        # Reuse the single bus's validated FFADO Discrete write and ensure the
        # hardware value was actually changed, rather than merely replying OK.
        if self.profile.get("family") != "motu":
            raise ValueError("This device uses a different routing interface")
        with self.helper.transaction():
            out = self._dest_output(bus_id)
            self.write_destination(bus_id, int(value))
            actual = int(self.helper.get_value(out["dest"]["path"], out["dest"]["kind"]))
            if actual != int(value):
                raise IOError(f"MOTU reported routing value {actual}, expected {value}")

    # ---------- where a bus is sent (Disabled, Phones, Analog 1-2 ...) ----------
    def _dest_options(self, current=None):
        return destination_options(self.profile, self.model, current)

    def _dest_output(self, out_id):
        out = self.outputs.get(out_id)
        if out is None or out["dest"] is None or not self._dest_options():
            raise ValueError(f"'{out_id}' has no destination setting on this device")
        return out

    def read_destination(self, out_id):
        dest = self._dest_output(out_id)["dest"]
        value = int(self.helper.get_value(dest["path"], dest["kind"]))
        return {"value": value, "options": self._dest_options(value)}

    def write_destination(self, out_id, value):
        dest = self._dest_output(out_id)["dest"]
        if int(value) not in [o["value"] for o in self._dest_options()]:
            raise ValueError("that destination isn't available on this device")
        self.helper.set_value(dest["path"], dest["kind"], int(value))

    # ---------- output (master) faders: Main, Phones, buses ----------
    def _output(self, out_id):
        out = self.outputs.get(out_id)
        if out is None or out["fader"] is None:
            raise ValueError(f"'{out_id}' has no level control on this device")
        return out

    def _save_mute_memory(self):
        self.config.save()

    @serialized_output
    def read_output(self, out_id):
        out = self._output(out_id)
        raw = self.helper.get_value(out["fader"]["path"], out["fader"]["kind"])
        spec = out.get("spec", self.out_spec)
        lo, hi = spec.get("min", 0), spec.get("max", 1)

        def norm(value):
            return to_percent(value, lo, hi) if spec["writable"] else 0

        if out["mute"]:                                            # real mute parameter (buses)
            mute = bool(self._read_scalar(out["mute"]))
            return {"name": out["name"], "level": norm(raw), "mute": mute, "emulated_mute": False}

        # Main/Phones: "muted" means we silenced it and remembered where the fader was.
        saved = self.mute_memory.get(out_id)
        if saved is not None and raw <= lo:
            return {"name": out["name"], "level": norm(saved), "mute": True, "emulated_mute": True}
        if saved is not None:                                      # level raised elsewhere: no longer muted
            del self.mute_memory[out_id]
            self._save_mute_memory()
        return {"name": out["name"], "level": norm(raw), "mute": False, "emulated_mute": True}

    @serialized_output
    def write_output(self, out_id, control, value):
        out = self._output(out_id)
        spec = out.get("spec", self.out_spec)
        if not spec["writable"]:
            raise ValueError("output level is read-only until a profile defines its range")
        fader = out["fader"]
        lo, hi = spec["min"], spec["max"]
        emulated = out["mute"] is None

        if control == "fader":
            raw = from_percent(value, lo, hi)
            if emulated and out_id in self.mute_memory:                # muted: remember the new position, stay silent
                self.mute_memory[out_id] = raw
                self._save_mute_memory()
                return
            self.helper.set_value(fader["path"], fader["kind"], raw)
        elif control == "mute" and not emulated:                   # buses have a real mute parameter
            self._write_scalar(out["mute"], bool(value))
        elif control == "mute":
            muted = out_id in self.mute_memory
            if value and not muted:                                # mute: remember the level, drop the output to zero
                self.mute_memory[out_id] = self.helper.get_value(fader["path"], fader["kind"])
                self._save_mute_memory()
                self.helper.set_value(fader["path"], fader["kind"], lo)
            elif not value and muted:                              # unmute: put the remembered level back
                restore = self.mute_memory.pop(out_id)
                self._save_mute_memory()
                self.helper.set_value(fader["path"], fader["kind"], restore)
        else:
            raise ValueError(f"{control} is not controllable on an output")
