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
        self.model = self._info(self.profile.get("model_element"))
        resolved = resolve_controls(self.device, self.profile, mixer["matrices"], self.columns, self.mixes)
        self.roles = resolved["roles"]
        self.out_spec = resolved["output_spec"]
        self.outputs = resolved["outputs"]
        self.chan = resolved["channels"]
        self.chan_specs = resolved["channel_specs"]
        self.mute_memory = config.mute_memory

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
            "features": features,
            "controls": {role: spec for role, (_, spec) in self.roles.items()},
            "globals": [c for c in self.device["controls"] if not c["path"].endswith(("/Info/Model", "/Info/IsStreaming"))],
        }

    def read_mix(self, mix):
        out = {}
        for col in self._visible_cols():
            entry = {"name": self.columns[col], "input": self.columns[col]}   # "input" is the fixed hardware name
            if "fader" in self.roles:
                path, spec = self.roles["fader"]
                raw = self.helper.get_cell(path, mix, col)
                lo, hi = spec.get("min", 0), spec.get("max", 1)
                entry["fader"] = to_percent(raw, lo, hi) if spec["writable"] else 0
            if "pan" in self.roles:
                path, spec = self.roles["pan"]
                raw = self.helper.get_cell(path, mix, col)
                lo, hi = spec.get("min", 0), spec.get("max", 1)
                entry["pan"] = pan_to_ui(raw, lo, hi) if spec["writable"] else 0.0
            for role in ("mute", "solo"):
                if role in self.roles:
                    entry[role] = bool(self.helper.get_cell(self.roles[role][0], mix, col))
            for role, control in self.chan.get(col, {}).items():
                value = self.helper.get_value(control["path"], control["kind"])
                entry[role] = bool(value) if role == "invert" else value
            out[f"ch/{col:02d}"] = entry      # zero-padded: JSON keys sort alphabetically
        return out

    def write(self, mix, strip, control, value):
        col = int(strip.split("/")[1])
        if not (0 <= col < len(self.columns)):
            raise ValueError("channel out of range")

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

        if control not in ("fader", "pan", "mute", "solo") or control not in self.roles:
            raise ValueError(f"{control} is not controllable on this device")
        path, spec = self.roles[control]
        if not spec["writable"]:
            raise ValueError(f"{control} is read-only until a profile defines its range")
        if not 0 <= mix < len(self.mixes):
            raise ValueError("mix out of range")
        lo, hi = spec.get("min", 0), spec.get("max", 1)
        if control == "fader":
            raw = from_percent(value, lo, hi)
        elif control == "pan":
            raw = pan_from_ui(value, lo, hi)
        else:
            raw = 1 if value else 0
        self.helper.set_cell(path, mix, col, raw)


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
        lo, hi = self.out_spec.get("min", 0), self.out_spec.get("max", 1)

        def norm(value):
            return to_percent(value, lo, hi) if self.out_spec["writable"] else 0

        if out["mute"]:                                            # real mute parameter (buses)
            mute = bool(self.helper.get_value(out["mute"]["path"], out["mute"]["kind"]))
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
        spec = self.out_spec
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
            self.helper.set_value(out["mute"]["path"], out["mute"]["kind"], 1 if value else 0)
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
