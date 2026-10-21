"""The FFADO mixer: reads and writes the connected device (any FFADO device, not one model).

Channels, buses and names come from FFADO matrix mixers. XML profiles provide
source-derived device-specific metadata; missing controls stay unavailable.
"""
from .profile_loader import (load_profile, resolve_mixer, resolve_controls,
                             visible_columns, destination_options, resolve_phones_assignment, bus_name, CHANNEL_WORDS)
from .controls import to_percent, from_percent, pan_to_ui, pan_from_ui
from .profiles.capabilities import enabled, probe_allowed, activate_internal_model, declared_path
from .peak_metering import meter_config, channel_destinations, normalize_peak
from .gain import UNITY, has_db_scale, scale as gain_scale, raw_to_db, db_to_raw, raw_to_ui, ui_to_raw
from functools import wraps
from copy import deepcopy
from .soft_mute import MuteJournal
import math



def input_pair_balance_from_raw(left, right):
    """Read the ordered Left/Right input balance from DICE/RME diagonals.

    ``write_input_pair_balance`` attenuates the quieter diagonal leg
    relative to the louder one, *not* by preserving the sum of the legs.
    The familiar (R-L)/(R+L) formula is correct for a mono input panned
    across two buses, but is NOT the inverse for a linked input pair.

    The hardware's <=16 native coefficient is its silence sentinel.  If
    both diagonal routes are silent the stereo balance is unknowable; do
    not display a fabricated centered pan.
    """
    left, right = float(left), float(right)
    if not math.isfinite(left) or not math.isfinite(right) or left < 0 or right < 0:
        raise ValueError('Invalid FFADO stereo matrix coefficient')
    left = left if left > 16 else 0.0
    right = right if right > 16 else 0.0
    peak = max(left, right)
    if not peak:
        return None
    # This is the inverse of write_input_pair_balance's piecewise
    # attenuation: pan=-1 leaves only Left; pan=+1 leaves only Right.
    return round((right - left) / peak, 4)


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
    from .interrogate import discover
    return discover()


class Mixer:
    def __init__(self, config, device_index=0, device=None, helper=None):
        self.config = config
        self.device = device if device is not None else load_device_info()["devices"][device_index]
        if helper is None:
            from .helper import FfadoHelper
            helper = FfadoHelper()
        self.helper = helper
        self.profile = self._find_profile()
        # MOTU pre-mk3 ConfigROM only identifies the generation. Ask FFADO for
        # its internal model enum before permitting any model-specific writes.
        model_suffix = self.profile.get('model_element')
        # Discovery already read the authoritative Info/Model on pre-mk3
        # MOTU hardware. Do not lose it if the metadata endpoint is absent
        # from a later inventory (e.g. a transient introspection failure).
        self.model = self.device.get('internal_model_id')
        if self.model is None:
            self.model = self._info(model_suffix)
        try:
            self.profile = activate_internal_model(self.profile, self.model)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        mixer = resolve_mixer(self.device, self.profile)
        if mixer is None or not mixer["matrices"].get("fader"):
            raise RuntimeError("No source-mapped writable gain matrix for this model")
        self.mixes, self.columns = mixer["rows"], mixer["columns"]
        self.matrix = mixer
        if has_db_scale(mixer["mode"]) and str(self.profile.get("mixer_matrix", {}).get("unity")) != str(UNITY):
            raise RuntimeError("Hardware profile is missing the source-defined 16384-count dB unity coefficient")
        router_suffix = declared_path(self.profile, "crossbar_routing")
        self.router_path = next((r["path"] for r in self.device.get("routers", [])
                                 if router_suffix and r["path"].endswith(router_suffix)), None)
        # The meter's hardware encoding and channel mapping must be present
        # on the exact resolved model profile; never infer from family name.
        self.meter_spec = meter_config(self.profile, self.matrix)
        self.meter_channels = channel_destinations(self.device, self.matrix, self.meter_spec)
        self._has_metering = None
        self._matrix_mutes = {}  # (bus, channel) -> original coefficient, for soft mute
        self._user_mutes = set()
        self._solos = {}  # mix -> set of soloed channel indices
        self._recovery_journal = None
        self._pending_recovery = {}
        self._mute_fault = None
        self._pending_output_recovery = set()
        resolved = resolve_controls(self.device, self.profile, mixer["matrices"], self.columns, self.mixes)
        self.roles = resolved["roles"]
        self.out_spec = resolved["output_spec"]
        self.outputs = resolved["outputs"]
        self.chan = resolved["channels"]
        self.chan_specs = resolved["channel_specs"]
        self.mute_memory = config.mute_memory
        self.guid = self.device['guid']
        self.nickname_path = next((c for c in self.device.get('controls', [])
            if c['path'].endswith('/Generic/Nickname') and c['kind'] == 'Text'), None)

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
        if has_db_scale(spec.get("type")):
            return raw_to_ui(raw, spec["type"])
        return to_percent(raw, spec.get("min", 0), spec.get("max", 1)) if math.isfinite(raw) else 0

    def _from_ui(self, ui, spec):
        if has_db_scale(spec.get("type")):
            return ui_to_raw(ui, spec["type"])
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
            "guid": getattr(self, 'guid', self.device.get('guid', '')),
            "profile": self.profile.get("device_profile"),
            "device": model.get("name") or self.profile.get("device_name") or f"FFADO device {self.device['guid']}",
            "mixes": [{"id": i, "name": bus_name(n)} for i, n in enumerate(self.mixes)],
            "outputs": [{"id": o["id"], "name": o["name"], "mix": o["mix"], "controllable": o["fader"] is not None,
                         "destination": o["dest"] is not None and bool(self._dest_options())}
                        for o in self.outputs.values()],
            "fader": {"writable": fader.get("writable", False)},
            "mute": {"writable": bool(self.roles.get("mute") or self._soft_mute())},
            "solo": {"writable": bool(self.roles.get("solo") or self._soft_mute())},
            "gain_scale": gain_scale(self.matrix["mode"]),
            "peak_metering": bool(self.router_path and self.meter_spec and self.meter_channels),
            "peak_meter": {"encoding": self.meter_spec["format"], "calibrated_dbfs": False,
                            "unit": self.meter_spec["unit"]} if self.router_path and self.meter_spec and self.meter_channels else None,
            "matrix": {"available": "fader" in self.roles, "path": self.matrix["path"],
                       "mode": self.matrix["mode"]},
            "router": bool(self.router_path),
            "bus_routing": bool(enabled(self.profile, "bus_destination") and
                                self._dest_options() and
                                any(out["dest"] is not None for out in self.outputs.values())),
            "phones_assignment": bool(resolve_phones_assignment(self.device, self.profile)),
            "features": features,
            "hardware_capabilities": self.profile.get('capabilities', {}),
            "controls": {role: spec for role, (_, spec) in self.roles.items()},
            "globals": [c for c in self.device["controls"] if not c["path"].endswith(("/Info/Model", "/Info/IsStreaming"))],
        }

    def _soft_mute(self):
        return enabled(self.profile, "software_mute_solo") and "mute" not in self.roles

    def attach_mute_recovery(self, *, debug=False):
        """Called after DeviceManager assigns this GUID's persistent config.

        A crash journal is *never* replayed automatically. Restoring an old
        nonzero gain can cause unexpected loud output after a power cycle.
        """
        self._recovery_journal = MuteJournal(self.config.path, self.guid,
                                            self.matrix['path'], enabled=not debug)
        try:
            self._pending_recovery = self._recovery_journal.load()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self._mute_fault = f'Cannot read software-mute recovery journal: {exc}'
            self._recovery_corrupt = True
            self._pending_recovery = {}
        # Existing emulated Main/Phones mutes were saved by older releases.
        # Do not restore them automatically on startup: levels may be unsafe.
        self._pending_output_recovery = set(self.mute_memory)
        if self._pending_recovery:
            print(f"FFADO mixer {self.guid}: {len(self._pending_recovery)} muted "
                  "matrix levels from an interrupted session. "
                  "Restore or discard in the web interface before changing mute/solo.")

    def mute_recovery_status(self):
        with self.helper.transaction():
            pending = sorted(self._pending_recovery)
            outputs = sorted(getattr(self, '_pending_output_recovery', set()))
            return {'pending': len(pending) + len(outputs), 'guid': self.guid,
                    'channels': [{'bus': mix + 1, 'input': col + 1}
                                 for mix, col in pending],
                    'outputs': outputs, 'fault': self._mute_fault,
                    'corrupt': bool(getattr(self, '_recovery_corrupt', False))}

    def resolve_mute_recovery(self, action):
        if action not in ('restore', 'discard'):
            raise ValueError('Recovery action must be restore or discard')
        with self.helper.transaction():
            if not self._recovery_journal:
                raise ValueError('No recovery journal is configured')
            if getattr(self, '_recovery_corrupt', False):
                if action == 'restore':
                    raise ValueError('Unreadable recovery journal cannot be restored safely')
                if self._recovery_journal.path:
                    self._recovery_journal.path.unlink(missing_ok=True)
                self._recovery_corrupt = False
                self._mute_fault = None
            if action == 'discard':
                # Keep current hardware settings untouched; discard only saved levels.
                self._recovery_journal.write({})
                count = len(self._pending_recovery) + len(self._pending_output_recovery)
                self._pending_recovery.clear()
                for out_id in list(self._pending_output_recovery):
                    self.mute_memory.pop(out_id, None)
                self._pending_output_recovery.clear()
                self._save_mute_memory()
                self._mute_fault = None
                return {'restored': 0, 'discarded': count, 'failed': 0}
            restored = skipped = failed = 0
            # Never overwrite a nonzero hardware value (somebody changed it).
            for key, saved in list(self._pending_recovery.items()):
                try:
                    mix, col = key
                    current = self._get_cell(self.roles['fader'][0], mix, col)
                    if not self._is_zero(current):
                        skipped += 1
                    elif not self._is_zero(saved):
                        self._set_cell(self.roles['fader'][0], mix, col, saved)
                        self._verify_cell(mix, col, saved)
                        restored += 1
                    else:
                        skipped += 1
                    del self._pending_recovery[key]
                    self._recovery_journal.write(self._pending_recovery)
                except Exception as exc:
                    failed += 1
                    self._mute_fault = f'Recovery of bus {key[0]+1}, input {key[1]+1}: {exc}'
            for out_id in list(self._pending_output_recovery):
                try:
                    out = self._output(out_id)
                    fader = out['fader']
                    spec = out.get('spec', self.out_spec)
                    saved = self.mute_memory[out_id]
                    current = self.helper.get_value(fader['path'], fader['kind'])
                    if float(current) > float(spec['min']):
                        skipped += 1
                    else:
                        self.helper.set_value(fader['path'], fader['kind'], saved)
                        self._verify_output(out, saved)
                        restored += 1
                    del self.mute_memory[out_id]
                    self._save_mute_memory()
                    self._pending_output_recovery.remove(out_id)
                except Exception as exc:
                    failed += 1
                    self._mute_fault = f'Output recovery for {out_id}: {exc}'
            if not failed:
                self._mute_fault = None
            return {'restored': restored, 'discarded': skipped, 'failed': failed,
                    'pending': len(self._pending_recovery) + len(self._pending_output_recovery)}

    @staticmethod
    def _is_zero(value):
        return abs(float(value)) <= 0.000001

    def _verify_cell(self, mix, col, expected):
        actual = self._get_cell(self.roles['fader'][0], mix, col)
        if not math.isfinite(float(actual)) or abs(float(actual) - float(expected)) > (1 if self.matrix['mode'] == 'dice_db' else 0.00001):
            raise IOError(f'FFADO readback mismatch at bus {mix + 1}, input {col + 1}: '
                          f'expected {expected}, received {actual}')
        return actual

    def _save_soft_mutes(self):
        if getattr(self, "_recovery_journal", None):
            # Include all currently suppressed cells. Write BEFORE muting so a
            # power loss during the D-Bus call leaves the restoration target.
            self._recovery_journal.write(self._matrix_mutes)

    def _require_recovery_resolved(self):
        if getattr(self, '_recovery_corrupt', False):
            raise RuntimeError('Software mute recovery journal is unreadable or mismatched; '
                               'correct it before using gain/mute controls')
        if getattr(self, "_pending_recovery", None) or getattr(self, '_pending_output_recovery', set()):
            raise RuntimeError('Previous software mute was interrupted. Restore or '
                               'discard pending levels before editing the matrix.')

    def _cell_base(self, mix, col):
        key = (mix, col)
        if key in self._matrix_mutes:
            return self._matrix_mutes[key]
        return self._get_cell(self.roles['fader'][0], mix, col)

    def _silenced(self, mix, col):
        solos = self._solos.get(mix, set())
        return (mix, col) in self._user_mutes or bool(solos and col not in solos)

    def _external_override(self, mix, col, raw):
        """External nonzero write wins. Never restore over it later."""
        key = (mix, col)
        if key in self._matrix_mutes and not self._is_zero(raw):
            del self._matrix_mutes[key]
            self._user_mutes.discard(key)
            # Solo can no longer be trusted for this bus; drop its logical state
            # and restore the *other* suppressed inputs without re-muting this one.
            if self._solos.get(mix):
                self._solos.pop(mix, None)
                for other in range(len(self.columns)):
                    other_key = (mix, other)
                    if other_key in self._matrix_mutes and other_key not in self._user_mutes:
                        self._restore_cell(mix, other)
            self._save_soft_mutes()
            self._mute_fault = f'External mixer change detected at bus {mix + 1}, input {col + 1}; mute/solo cancelled for that channel.'
            return True
        return False

    def _restore_cell(self, mix, col):
        key = (mix, col)
        if key not in self._matrix_mutes:
            return
        saved = self._matrix_mutes[key]
        current = self._get_cell(self.roles['fader'][0], mix, col)
        if not self._is_zero(current):
            self._external_override(mix, col, current)
            return
        if not self._is_zero(saved):
            self._set_cell(self.roles['fader'][0], mix, col, saved)
            self._verify_cell(mix, col, saved)
        # Only release the recovery journal entry after verified restoration.
        del self._matrix_mutes[key]
        self._save_soft_mutes()

    def _reconcile_cell(self, mix, col):
        """Read/modify/verify with a durable journal and external-change guard."""
        path = self.roles['fader'][0]
        key = (mix, col)
        current = self._get_cell(path, mix, col)
        if self._external_override(mix, col, current):
            return
        if self._silenced(mix, col):
            if key not in self._matrix_mutes:
                self._matrix_mutes[key] = current
                try:
                    self._save_soft_mutes()  # persist BEFORE the zero write
                except BaseException:
                    del self._matrix_mutes[key]
                    raise
            if not self._is_zero(current):
                self._set_cell(path, mix, col, 0)
                self._verify_cell(mix, col, 0)
        else:
            self._restore_cell(mix, col)

    def shutdown_soft_mutes(self):
        """Best-effort clean-exit restoration; failures retain the journal."""
        if not getattr(self, '_recovery_journal', None) or self._pending_recovery or self._pending_output_recovery or getattr(self, '_recovery_corrupt', False):
            return
        with self.helper.transaction():
            self._solos.clear()
            self._user_mutes.clear()
            for mix, col in list(self._matrix_mutes):
                try:
                    self._restore_cell(mix, col)
                except Exception as exc:
                    print(f'FFADO: could not restore bus {mix+1}, input {col+1}: {exc}')
            for out_id in list(self.mute_memory):
                try:
                    out = self._output(out_id)
                    fader = out['fader']
                    spec = out.get('spec', self.out_spec)
                    current = self.helper.get_value(fader['path'], fader['kind'])
                    saved = self.mute_memory[out_id]
                    if float(current) <= float(spec['min']):
                        self.helper.set_value(fader['path'], fader['kind'], saved)
                        self._verify_output(out, saved)
                    del self.mute_memory[out_id]
                    self._save_mute_memory()
                except Exception as exc:
                    print(f'FFADO: could not restore output {out_id}: {exc}')

    def _write_gain_cell(self, mix, col, raw):
        """All matrix/fader/stereo gain edits share the same recovery guard."""
        self._require_recovery_resolved()
        key = (mix, col)
        path = self.roles['fader'][0]
        if self._soft_mute() and key in self._matrix_mutes:
            current = self._get_cell(path, mix, col)
            if not self._external_override(mix, col, current):
                old = self._matrix_mutes[key]
                self._matrix_mutes[key] = raw
                try: self._save_soft_mutes()
                except BaseException:
                    self._matrix_mutes[key] = old
                    raise
                return True  # saved for unmute; actual hardware stays zero
        self._set_cell(path, mix, col, raw)
        return False

    def write_bus_balance(self, bus, col, value):
        """Source-derived stereo bus balance: FFADO matrixmixer.py formulas."""
        if 'fader' not in self.roles or not 0 <= bus < len(self.mixes) - 1 or bus % 2:
            raise ValueError('Stereo balance requires an odd/even output pair')
        value = max(-1., min(1., float(value)))
        with self.helper.transaction():
            self._require_recovery_resolved()
            left, right = self._cell_base(bus, col), self._cell_base(bus + 1, col)
            total = float(left) + float(right)
            lnew = round(total * (1 - value) / 2)
            rnew = round(total - lnew)
            for m, raw in ((bus, lnew), (bus+1, rnew)):
                self._write_gain_cell(m, col, raw)

    def forget_input_pair_balance(self, left, right, bus=None):
        """Discard this bus's temporary balance reference on link/unlink.

        ``bus=None`` is retained for callers explicitly clearing all buses.
        """
        affected = {int(left.split('/')[-1]), int(right.split('/')[-1])}
        with self.helper.transaction():
            cache = getattr(self, '_input_pair_balance_cache', {})
            for key in list(cache):
                if (bus is None or key[0] == bus) and affected.intersection(key[1:]):
                    del cache[key]

    def write_input_pair_balance(self, bus, left_col, right_col, value):
        """Balance two input channels without ever making new matrix routes.

        A linked *input* pair differs from one mono input panned into two
        outputs. Left input goes to the left output, Right input to the right
        output; custom crosspoints must remain exactly as the user configured.
        Only the two diagonal coefficients are eligible for adjustment.

        Keep a volatile route mask/reference so returning from a hard-L/R
        balance can restore a side this control itself just attenuated to zero.
        External edits invalidate that reference; a route that was already
        disconnected when balance was first touched remains disconnected.
        """
        if (not 0 <= bus < len(self.mixes) - 1 or bus % 2 or
                left_col == right_col or
                not all(0 <= col < len(self.columns) for col in (left_col, right_col)) or
                self.matrix['mode'] not in ('dice_db', 'rme_db')):
            raise ValueError('Stereo input balance requires two distinct inputs and a linked output pair')
        value = float(value)
        if not math.isfinite(value) or not -1 <= value <= 1:
            raise ValueError('Stereo balance must be between -1 and 1')
        with self.helper.transaction():
            self._require_recovery_resolved()
            current = (float(self._matrix_raw(bus, left_col)),
                       float(self._matrix_raw(bus + 1, right_col)))
            cache = getattr(self, '_input_pair_balance_cache', None)
            if cache is None:
                cache = self._input_pair_balance_cache = {}
            key = (bus, left_col, right_col)
            remembered = cache.get(key)
            # Exact comparisons are intentional: coefficients are integers on
            # DICE/RME, and all our writes are verified by their readbacks.
            if remembered is None or remembered['last'] != current:
                remembered = {'enabled': (current[0] > 0, current[1] > 0),
                              'reference': max(current), 'last': current}
            peak = remembered['reference']
            left = round(peak * (1 - max(0., value))) if remembered['enabled'][0] else 0
            right = round(peak * (1 + min(0., value))) if remembered['enabled'][1] else 0
            target = (left, right)
            attempted = []
            try:
                for point, old, new in (((bus, left_col), current[0], left),
                                        ((bus + 1, right_col), current[1], right)):
                    if old != new:
                        # Record before writing: even failed readback can mean
                        # the hardware accepted the new coefficient.
                        attempted.append((point, old))
                        self._write_gain_cell(*point, new)
            except Exception as exc:
                cache.pop(key, None)
                errors = []
                for point, old in reversed(attempted):
                    try:
                        self._write_gain_cell(*point, old)
                    except Exception as rollback_exc:
                        errors.append(str(rollback_exc))
                if errors:
                    raise RuntimeError('Stereo input balance failed; hardware rollback '
                                       'may be incomplete: ' + '; '.join(errors)) from exc
                raise
            remembered['last'] = target
            cache[key] = remembered

    def read_bus_balance(self, bus, col):
        left, right = self._cell_base(bus, col), self._cell_base(bus+1, col)
        return round((right - left) / (right + left), 2) if left + right else 0

    def read_stereo_level(self, bus, col):
        if bus % 2 or bus + 1 >= len(self.mixes):
            raise ValueError('Invalid left bus index')
        v0=self._cell_base(bus,col)
        v1=self._cell_base(bus+1,col)
        return self._to_ui(max(v0, v1), self.roles['fader'][1])

    def write_stereo_level(self, bus, col, ui):
        if bus % 2 or bus + 1 >= len(self.mixes):
            raise ValueError('Invalid left bus index')
        spec=self.roles['fader'][1]
        with self.helper.transaction():
            self._require_recovery_resolved()
            left=self._cell_base(bus,col)
            right=self._cell_base(bus+1,col)
            balance=(right-left)/(right+left) if (right+left) else 0
            # The strip displays the louder matrix leg, not the average.
            # Preserve the current L/R balance when moving that strip.
            peak = self._from_ui(ui, spec)
            old_peak = max(left, right)
            if old_peak > 0:
                new = (round(peak * left / old_peak), round(peak * right / old_peak))
            else:
                # A completely disconnected input has no existing L/R route.
                # Moving its strip must not activate BOTH outputs and create
                # unintended mono crossfeed. Connect it in the matrix first.
                return  # no pre-existing path: never create one from a fader
            for m,v in ((bus,new[0]),(bus+1,new[1])):
                self._write_gain_cell(m, col, v)
            # An independent fader edit changes a pair's balance reference.
            cache = getattr(self, '_input_pair_balance_cache', {})
            for key in list(cache):
                if key[0] == bus and col in key[1:]:
                    del cache[key]

    def peak_snapshot(self):
        """Read only the source-declared DICE EAP router peaks.

        Destination names and column indexes come directly from FFADO's
        matrix row labels. Meters are pre-mixer router destination readings,
        not per-bus or post-fader measurements.
        """
        empty = {'available': False, 'channels': {}, 'destinations': {},
                 'meter': self.meter_spec, 'guid': self.guid}
        if not self.router_path or not self.meter_spec or not self.meter_channels:
            return empty
        if self._has_metering is None:
            self._has_metering = bool(self.helper.router_call(self.router_path, 'hasPeakMetering'))
        if not self._has_metering:
            return empty
        values = self.helper.router_call(self.router_path, 'getPeakValues')
        raw_destinations = {}
        clean_destinations = {}
        for name, raw in values:
            item = normalize_peak(raw, self.meter_spec)
            if item is not None:
                raw_destinations[str(name)] = item['raw']
                clean_destinations[str(name)] = item
        channels = {index: {'destination': dest, **clean_destinations[dest]}
                    for index, dest in self.meter_channels.items()
                    if dest in clean_destinations}
        return {'available': True, 'guid': self.guid, 'meter': self.meter_spec,
                'channels': channels, 'destination_levels': clean_destinations,
                'destinations': raw_destinations}


    @serialized_output
    def read_mix(self, mix, *, stereo_bus=False):
        """Read a bus and (optionally) its linked right bus in one transaction.

        A linked bus derives its fader and balance from the *same* pair of
        native matrix coefficients. No coefficients are changed by a read.
        """
        if stereo_bus and (mix % 2 or mix + 1 >= len(self.mixes) or
                           self.matrix["mode"] not in ("dice_db", "rme_db")):
            raise ValueError("Stereo state requires a supported left output bus")
        if not 0 <= mix < len(self.mixes):
            raise ValueError("mix out of range")
        out = {}
        for col in self._visible_cols():
            entry = {"name": self.columns[col], "input": self.columns[col]}   # "input" is the fixed hardware name
            if "fader" in self.roles:
                path, spec = self.roles["fader"]
                raw = self._get_cell(path, mix, col)
                saved = self._matrix_mutes.get((mix, col))
                if saved is not None and self._soft_mute() and not self._is_zero(raw):
                    with self.helper.transaction():
                        self._external_override(mix, col, raw)
                    saved = None
                entry["fader"] = self._to_ui(saved if saved is not None else raw, spec) if spec["writable"] else 0
                if stereo_bus:
                    # Matrix editor, stereo fader, and balance must all use
                    # effective hardware/saved-mute coefficients, not a cached
                    # fader from the left bus or two independent API reads.
                    left = float(self._matrix_raw(mix, col))
                    right = float(self._matrix_raw(mix + 1, col))
                    entry["fader"] = self._to_ui(max(left, right), spec)
                    entry["pan"] = (round((right - left) / (right + left), 4)
                                    if max(left, right) > 16 else None)
                    entry["pan_available"] = entry["pan"] is not None
                    entry["matrix_legs"] = {
                        "left_db": raw_to_db(left, self.matrix["mode"]),
                        "right_db": raw_to_db(right, self.matrix["mode"]),
                    }
                    # Used only by the API when combining two linked inputs.
                    entry["_matrix_raw"] = [left, right]
                if self._soft_mute():
                    entry["mute"] = (mix, col) in getattr(self, '_user_mutes', set()) or raw == 0
                    entry["solo"] = col in getattr(self, '_solos', {}).get(mix, set())
            if "pan" in self.roles and not stereo_bus:
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

        if self._soft_mute() and control in ("mute", "solo") and "fader" in self.roles:
            if not hasattr(self, '_user_mutes'): self._user_mutes = set()
            if not hasattr(self, '_solos'): self._solos = {}
            with self.helper.transaction():
                self._require_recovery_resolved()
                # Detect externally changed cells before changing logical state.
                for key in list(self._matrix_mutes):
                    self._external_override(*key, self._get_cell(self.roles['fader'][0], *key))
                prior_mutes = set(self._user_mutes)
                prior_solos = deepcopy(self._solos)
                try:
                    if control == 'mute':
                        if value: self._user_mutes.add((mix, col))
                        else: self._user_mutes.discard((mix, col))
                        self._reconcile_cell(mix, col)
                    else:
                        solos = self._solos.setdefault(mix, set())
                        if value: solos.add(col)
                        else: solos.discard(col)
                        if not solos: self._solos.pop(mix, None)
                        for index in range(len(self.columns)):
                            self._reconcile_cell(mix, index)
                    self._mute_fault = None
                except Exception as exc:
                    self._user_mutes = prior_mutes
                    self._solos = prior_solos
                    # Best-effort rollback to the previous logical state.
                    # Any hardware writes that cannot be undone keep a journal.
                    rollback_errors = []
                    for key in list(self._matrix_mutes):
                        if key[0] == mix:
                            try: self._reconcile_cell(*key)
                            except Exception as failure: rollback_errors.append(str(failure))
                    self._mute_fault = f'Mute/solo failed: {exc}'
                    if rollback_errors:
                        self._mute_fault += '; rollback incomplete: ' + '; '.join(rollback_errors)
                    raise RuntimeError(self._mute_fault) from exc
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
            if self._soft_mute():
                with self.helper.transaction():
                    self._require_recovery_resolved()
                    key = (mix, col)
                    if key in self._matrix_mutes:
                        actual = self._get_cell(path, mix, col)
                        if not self._external_override(mix, col, actual):
                            old = self._matrix_mutes[key]
                            self._matrix_mutes[key] = self._from_ui(value, spec)
                            try: self._save_soft_mutes()
                            except BaseException:
                                self._matrix_mutes[key] = old
                                raise
                            return
            raw = self._from_ui(value, spec)
        elif control == "pan":
            raw = pan_from_ui(value, lo, hi)
        else:
            raw = 1 if value else 0
        if control == 'fader' and self._soft_mute():
            with self.helper.transaction():
                self._write_gain_cell(mix, col, raw)
        else:
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
    def _matrix_raw(self, mix, col):
        """Read effective gain, respecting external hardware changes."""
        key = (mix, col)
        actual = self._get_cell(self.roles['fader'][0], mix, col)
        if self._soft_mute() and key in self._matrix_mutes:
            if not self._external_override(mix, col, actual):
                return self._matrix_mutes[key]
        return actual

    def matrix_snapshot(self):
        if "fader" not in self.roles:
            raise ValueError("No writable gain matrix exposed for this device")
        path, spec = self.roles["fader"]
        mode = spec.get("type")
        with self.helper.transaction():
            raw_values = [[self._matrix_raw(mix, col) for mix in range(len(self.mixes))]
                          for col in range(len(self.columns))]
        values = [[self._to_ui(raw, spec) for raw in row] for row in raw_values]
        data = {"inputs": self.columns, "outputs": self.mixes, "values": values,
                "mode": self.matrix["mode"]}
        if has_db_scale(mode):
            data["gain_scale"] = gain_scale(mode)
            data["db_values"] = [[None if (db := raw_to_db(raw, mode)) is None
                                   else round(db, 3) for raw in row] for row in raw_values]
        return data

    def matrix_set(self, input_index, output_index, value=None, *, db=None, use_db=False):
        """Write one matrix cell. Old percentage clients remain supported.

        New clients submit {db: -12.3} or {db: null} for precise levels and
        silence; these values never round-trip through a percentage scale.
        """
        if "fader" not in self.roles or not self.roles["fader"][1]["writable"]:
            raise ValueError("No writable gain matrix on this device")
        if not (0 <= input_index < len(self.columns) and 0 <= output_index < len(self.mixes)):
            raise ValueError("Invalid mixer matrix coordinate")
        path, spec = self.roles['fader']
        mode = spec.get('type')
        if use_db:
            if not has_db_scale(mode):
                raise ValueError("This hardware profile does not support dB matrix edits")
            raw = db_to_raw(db, mode)
        else:
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError("Mixer gain must be between 0 and 100")
            raw = self._from_ui(value, spec)
        key = (output_index, input_index)
        with self.helper.transaction():
            deferred = self._write_gain_cell(output_index, input_index, raw)
            # The user explicitly edited a matrix cell. Don't later revive a
            # route based on a stale balance gesture's remembered coefficients.
            cache = getattr(self, '_input_pair_balance_cache', {})
            for pair in list(cache):
                if (output_index, input_index) in ((pair[0],pair[1]), (pair[0]+1,pair[2])):
                    del cache[pair]
            # If soft-muted, the effective level is the intended restored
            # value, not the silent physical crosspoint.
            applied = self._matrix_raw(output_index, input_index)
        result = {"ok": True, "value": self._to_ui(applied, spec),
                  "deferred": deferred}
        if has_db_scale(mode):
            native_db = raw_to_db(applied, mode)
            result.update(db=None if native_db is None else round(native_db, 3),
                          native=int(applied))
        return result

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
            if before == source or (not source and before.startswith('Mute:')):
                return
            # Match FFADO's OutputSwitcher: disconnect the previous route,
            # then connect the requested source. Disconnection mutes only
            # this destination; it does not clear the whole router.
            if before and not before.startswith('Mute:'):
                if not self.helper.router_call(self.router_path, "setConnectionState", before, destination, False):
                    raise ValueError("FFADO could not disconnect the previous route")
            if source:
                if not self.helper.router_call(self.router_path, "setConnectionState", source, destination, True):
                    if before:
                        self.helper.router_call(self.router_path, "setConnectionState", before, destination, True)
                    raise ValueError("FFADO rejected that routing connection")
            actual = str(self.helper.router_call(self.router_path, "getSourceForDestination", destination))
            if not source and actual.startswith('Mute:'):
                return  # FFADO's RouterConfig::muteRoute sets Mute:00, not empty.
            if actual != source:
                raise IOError("FFADO routing readback did not match the requested connection")

    # ---------- source-defined MOTU mix-bus destination routing ----------
    def bus_routing_snapshot(self):
        """Output-assignment matrix; unlike matrix_snapshot this NEVER reads gain.

        On pre-mk3 MOTU hardware each Mix_dest scalar selects one destination
        for that bus. Other buses may use the same destination. There is no
        general per-output crossbar exposed on this hardware.
        """
        if not enabled(self.profile, "bus_destination"):
            raise ValueError("No bus destination routing mapped for this device")
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
        result = {"buses": buses, "destinations": options, "kind": "motu_mix_dest"}
        # Phones assign is independent of the four bus Mix_dest selectors.
        # Report it only for an explicitly mapped, physically discovered
        # Discrete control; never fabricate a control for unsupported models.
        control = resolve_phones_assignment(self.device, self.profile)
        if control is not None:
            with self.helper.transaction():
                value = int(self.helper.get_value(control['path'], control['kind']))
            result['phones'] = {'value': value, 'options': self._dest_options(value)}
        return result

    def bus_routing_set(self, bus_id, value):
        # Reuse the single bus's validated FFADO Discrete write and ensure the
        # hardware value was actually changed, rather than merely replying OK.
        if not enabled(self.profile, "bus_destination"):
            raise ValueError("No bus destination routing mapped for this device")
        with self.helper.transaction():
            out = self._dest_output(bus_id)
            self.write_destination(bus_id, int(value))
            actual = int(self.helper.get_value(out["dest"]["path"], out["dest"]["kind"]))
            if actual != int(value):
                raise IOError(f"MOTU reported routing value {actual}, expected {value}")

    def write_phones_assignment(self, value):
        """Set the MOTU headphone source, then verify what FFADO reports.

        This control does not alter mix destinations or matrix volumes.
        """
        control = resolve_phones_assignment(self.device, self.profile)
        if control is None:
            raise ValueError('Phones destination is not supported by this device')
        if type(value) is not int or value not in [opt['value'] for opt in self._dest_options()]:
            raise ValueError('Phones destination is not available for this model')
        with self.helper.transaction():
            before = int(self.helper.get_value(control['path'], control['kind']))
            if before == value:
                return value
            self.helper.set_value(control['path'], control['kind'], value)
            actual = int(self.helper.get_value(control['path'], control['kind']))
            if actual != value:
                raise IOError(f'FFADO reported Phones destination {actual}, expected {value}')
            return actual

    # ---------- where a bus is sent (Disabled, Phones, Analog 1-2 ...) ----------
    def _dest_options(self, current=None):
        return destination_options(self.profile, self.model, current) if enabled(self.profile, "bus_destination") else []

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

    def _verify_output(self, out, expected):
        fader = out['fader']
        actual = self.helper.get_value(fader['path'], fader['kind'])
        if not math.isfinite(float(actual)) or abs(float(actual) - float(expected)) > 0.00001:
            raise IOError(f'FFADO rejected output level for {out["name"]}: '
                          f'expected {expected}, received {actual}')
        return actual

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
            getattr(self, '_pending_output_recovery', set()).discard(out_id)
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

        if emulated and getattr(self, '_pending_output_recovery', set()) and out_id in self._pending_output_recovery:
            raise RuntimeError('This output has a pending mute recovery. Restore or keep current levels first.')
        if control == "fader":
            raw = from_percent(value, lo, hi)
            if emulated and out_id in self.mute_memory:
                old = self.mute_memory[out_id]
                actual = self.helper.get_value(fader['path'], fader['kind'])
                if float(actual) > float(lo):
                    # External device adjustment overrides our saved mute.
                    del self.mute_memory[out_id]
                    self._save_mute_memory()
                else:
                    self.mute_memory[out_id] = raw
                    try: self._save_mute_memory()
                    except BaseException:
                        self.mute_memory[out_id] = old
                        raise
                    return
            self.helper.set_value(fader['path'], fader['kind'], raw)
            self._verify_output(out, raw)
        elif control == "mute" and not emulated:
            self._write_scalar(out["mute"], bool(value))
            if bool(self._read_scalar(out["mute"])) != bool(value):
                raise IOError('FFADO did not acknowledge output mute change')
        elif control == "mute":
            muted = out_id in self.mute_memory
            if value and not muted:
                current = self.helper.get_value(fader['path'], fader['kind'])
                self.mute_memory[out_id] = current
                try: self._save_mute_memory()  # persist before lowering output
                except BaseException:
                    del self.mute_memory[out_id]
                    raise
                try:
                    self.helper.set_value(fader['path'], fader['kind'], lo)
                    self._verify_output(out, lo)
                except Exception:
                    # If it never reached zero, release the saved state; if
                    # silence did apply, keep it for retry/recovery.
                    actual = self.helper.get_value(fader['path'], fader['kind'])
                    if float(actual) > float(lo):
                        del self.mute_memory[out_id]
                        self._save_mute_memory()
                    raise
            elif not value and muted:
                current = self.helper.get_value(fader['path'], fader['kind'])
                if float(current) > float(lo):
                    # Someone else modified the output. Do not overwrite it.
                    del self.mute_memory[out_id]
                    self._save_mute_memory()
                    return
                restore = self.mute_memory[out_id]
                self.helper.set_value(fader['path'], fader['kind'], restore)
                self._verify_output(out, restore)
                # Only remove the saved level AFTER a verified write.
                del self.mute_memory[out_id]
                self._save_mute_memory()
        else:
            raise ValueError(f"{control} is not controllable on an output")
