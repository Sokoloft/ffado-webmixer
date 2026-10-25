"""The FFADO mixer: reads and writes the connected device (any FFADO device, not one model).

Channels, buses and names come from FFADO matrix mixers. XML profiles provide
source-derived device-specific metadata; missing controls stay unavailable.
"""
from .profile_loader import (load_profile, resolve_mixer, resolve_controls,
                             visible_columns, destination_options, resolve_phones_assignment, bus_name, CHANNEL_WORDS)
from .controls import to_percent, from_percent, pan_to_ui, pan_from_ui
from .profiles.capabilities import enabled, probe_allowed, activate_internal_model, declared_path
from .peak_metering import meter_config, channel_destinations, normalize_peak
from .gain import (UNITY, has_db_scale, scale as gain_scale, raw_to_db, db_to_raw,
                   raw_to_ui, ui_to_raw, motu_display_scale)
from copy import deepcopy
from .soft_mute import MuteJournal
from .mixer_outputs import OutputControls, serialized_output
from .mixer_routing import RoutingControls
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


def load_device_info(config=None):
    """Discover the currently connected FFADO hardware; never persist its topology.

    XML profiles describe known controls and model-specific interpretation.
    The live D-Bus tree supplies the actual available paths and matrix dimensions.
    """
    print("Interrogating connected FFADO hardware...")
    from .interrogate import discover
    return discover()


class Mixer(RoutingControls, OutputControls):
    """Resolve device state and share gain/recovery guards across its controls.

    RoutingControls provides matrix and destination APIs; OutputControls
    provides master levels and persistent output mute.
    """

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
        # DICE mixer input row labels are snapshots taken during discovery:
        #   Mixer/In:01\n(Mic/Lin/Inst:01)
        # Mixer/In:01 is the CrossbarRouter *destination*. Its selected source
        # may change while ffado-webmixer is running. Retain that fixed mapping
        # separately from the immutable column IDs and hardware controls.
        self._router_input_columns = {}
        self._router_input_sources = {}
        if self.router_path and self.matrix.get('transposed'):
            matrix_info = next((item for item in self.device.get('matrices', [])
                                if item.get('path') == self.matrix['path']), None)
            if matrix_info:
                for index, name in enumerate(matrix_info.get('row_names', [])):
                    destination = str(name).split('\n', 1)[0].strip()
                    if (index < len(self.columns) and
                            destination.startswith('Mixer/In:')):
                        self._router_input_columns[destination] = index
        # The meter's hardware encoding and channel mapping must be present
        # on the exact resolved model profile; never infer from family name.
        self.meter_spec = meter_config(self.profile, self.matrix)
        self.meter_channels = channel_destinations(self.device, self.matrix, self.meter_spec)
        self._has_metering = None
        self._matrix_mutes = {}  # (bus, channel) -> original coefficient, for soft mute
        self._stereo_level_memory = {}  # (linked bus, channel) -> last explicit fader routing
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
            if not math.isfinite(float(actual)) or (not (self._is_zero(value) and self._is_zero(actual))
                                                     and abs(float(actual) - float(value)) > 1):
                raise IOError("FFADO did not apply mixer value; check hardware mixer state")

    def _to_ui(self, raw, spec):
        raw = float(raw)
        if has_db_scale(spec.get("type")):
            return raw_to_ui(raw, spec["type"])
        if spec.get('step') and spec.get('max', 1) > spec.get('min', 0):
            # Integer percentages cannot represent every MOTU 0..128 step.
            # Retain enough precision to read and write any native level.
            if not math.isfinite(raw):
                return 0
            return round(max(0., min(100., (raw - spec.get('min', 0)) * 100.
                                        / (spec['max'] - spec.get('min', 0)))), 5)
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
    def _fader_display_scale(self, spec, feature):
        if (self.profile.get('family') == 'motu'
                and self.profile.get('internal_model_id') in (1, 2, 3, 4, 6)
                and enabled(self.profile, feature)
                and spec.get('min') == 0 and spec.get('max') == 128):
            return motu_display_scale()
        return gain_scale(spec.get('type'))

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
                if role == 'gain' and self.profile.get('family') == 'motu':
                    features[role]['label'] = 'Gain'
        return {
            "guid": getattr(self, 'guid', self.device.get('guid', '')),
            "profile": self.profile.get("device_profile"),
            "device": model.get("name") or self.profile.get("device_name") or f"FFADO device {self.device['guid']}",
            "mixes": [{"id": i, "name": bus_name(n)} for i, n in enumerate(self.mixes)],
            "outputs": [{"id": o["id"], "name": o["name"], "mix": o["mix"], "controllable": o["fader"] is not None,
                         "destination": o["dest"] is not None and bool(self._dest_options()),
                         "gain_scale": self._fader_display_scale(o.get('spec', self.out_spec), 'output_level')}
                        for o in self.outputs.values()],
            "fader": {"writable": fader.get("writable", False)},
            "mute": {"writable": bool(self.roles.get("mute") or self._soft_mute())},
            "solo": {"writable": bool(self.roles.get("solo") or self._soft_mute())},
            "gain_scale": gain_scale(self.matrix["mode"]),
            "fader_scale": self._fader_display_scale(fader, 'matrix_gain'),
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

    def _is_zero(self, value):
        """FFADO's native DICE/RME -infinity range includes coefficients 0..16.

        Some devices return 16 after setValue(0); treating that readback as
        an external edit discards the saved unmute level and breaks recovery.
        Other matrix families continue to require an actual zero.
        """
        raw = float(value)
        return (0 <= raw <= 16) if has_db_scale(self.matrix['mode']) else abs(raw) <= 0.000001

    def _verify_cell(self, mix, col, expected):
        actual = self._get_cell(self.roles['fader'][0], mix, col)
        if not math.isfinite(float(actual)) or (not (self._is_zero(expected) and self._is_zero(actual))
                                                 and abs(float(actual) - float(expected)) >
                                                 (1 if has_db_scale(self.matrix['mode']) else 0.00001)):
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

    def write_input_pair_balance(self, bus, left_col, right_col, value, *, activate_missing=False):
        """Balance two input channels without ever making new matrix routes.

        A linked *input* pair differs from one mono input panned into two
        outputs. Left input goes to the left output, Right input to the right
        output; custom crosspoints must remain exactly as the user configured.
        Only the two diagonal coefficients are eligible for adjustment.

        Keep a volatile route mask/reference so returning from a hard-L/R
        balance can restore a side this control itself just attenuated to zero.
        External edits invalidate that reference. An explicit UI pan gesture
        may opt in to ``activate_missing``: it completes a missing DIAGONAL
        stereo route at the existing leg's level, without changing either
        cross-route. Pairing itself still never changes hardware routing.
        No route is created when both diagonals are disconnected.
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
            if (remembered is None or remembered['last'] != current or
                    (activate_missing and any(v > 16 for v in current) and
                     not all(remembered['enabled']))):
                active = (current[0] > 16, current[1] > 16)
                # FFADO's 0..16 is -infinity, not a small audible level.
                # Only an explicit stereo pan gesture may complete an absent
                # diagonal, and only when there is a real reference level.
                make_stereo = activate_missing and any(active)
                remembered = {'enabled': (True, True) if make_stereo else active,
                              'reference': max(current[0] if active[0] else 0,
                                               current[1] if active[1] else 0),
                              'last': current}
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

    def write_stereo_levels(self, bus, channels, ui):
        """Set an entire stereo bus's visible fader level, including at -infinity.

        ``channels`` is [(column, 'mono'|'left'|'right'), ...]. Moving an
        *unlinked mono* channel's fader from silence explicitly establishes a
        centered signal on both bus legs. A *linked input pair* establishes
        only its respective diagonal: left input -> left bus; right input ->
        right bus. Existing routing, including custom crosspoints, is scaled
        without changing its topology.

        Remember only routes silenced by THIS fader so raising it from zero
        can restore the previous L/R ratio. Never resurrect a route that was
        disconnected through the matrix editor or another client.
        """
        if (type(bus) is not int or bus % 2 or bus < 0 or
                bus + 1 >= len(self.mixes) or
                self.matrix['mode'] not in ('dice_db', 'rme_db')):
            raise ValueError('Invalid linked output bus')
        if not channels or len(channels) > 2:
            raise ValueError('A stereo bus fader needs one mono input or one stereo input pair')
        if len(channels) == 2 and {side for _, side in channels} != {'left', 'right'}:
            raise ValueError('A linked stereo input requires Left and Right channels')
        if (any(type(col) is not int or not 0 <= col < len(self.columns) or
                side not in ('mono', 'left', 'right') for col, side in channels) or
                len({col for col, _ in channels}) != len(channels)):
            raise ValueError('Invalid or duplicated stereo fader channel')
        peak = self._from_ui(ui, self.roles['fader'][1])  # validates 0..100
        if not math.isfinite(float(peak)) or peak < 0:
            raise ValueError('Invalid mixer volume')

        with self.helper.transaction():
            self._require_recovery_resolved()
            memory = getattr(self, '_stereo_level_memory', None)
            if memory is None:
                memory = self._stereo_level_memory = {}
            before_memory = deepcopy(memory)
            targets = []
            updates = {}
            for col, side in channels:
                key = (bus, col)
                current = (float(self._cell_base(bus, col)),
                           float(self._cell_base(bus + 1, col)))
                previous = memory.get(key)
                # Coefficients are hardware integers, including the 0..16
                # native silence sentinel. If an external edit changed either
                # coefficient, a cached route is no longer trustworthy.
                if (previous is not None and
                        (previous.get('side') != side or not all(
                            a == b or (self._is_zero(a) and self._is_zero(b)) or
                            (a > 16 and b > 16 and abs(a - b) <= 1)
                            for a, b in zip(previous['last'], current)))):
                    previous = None
                    memory.pop(key, None)
                active = tuple(v if v > 16 else 0.0 for v in current)
                old_peak = max(active)
                if old_peak > 0:
                    ratios = (active[0] / old_peak, active[1] / old_peak)
                elif previous is not None:
                    ratios = previous['ratios']
                elif side == 'left':
                    ratios = (1.0, 0.0)
                elif side == 'right':
                    ratios = (0.0, 1.0)
                else:
                    # A single mono source in a stereo bus is centered.
                    # This action was explicitly requested by raising its
                    # fader; linking buses alone does not change any route.
                    ratios = (1.0, 1.0)
                new = (round(peak * ratios[0]), round(peak * ratios[1]))
                new = tuple(v if v > 16 else 0 for v in new)
                for leg, (old_value, new_value) in enumerate(zip(current, new)):
                    if (old_value != new_value and not
                            (self._is_zero(old_value) and self._is_zero(new_value))):
                        targets.append(((bus + leg, col), old_value, new_value))
                # Do not create recovery history from a fader already at zero.
                if peak > 16 or old_peak > 0 or previous is not None:
                    updates[key] = {'last': new, 'ratios': ratios, 'side': side}
                else:
                    memory.pop(key, None)

            attempted = []
            try:
                for point, old, new in targets:
                    # Include an attempted write before readback: D-Bus can
                    # report a failure after the device applied the change.
                    attempted.append((point, old))
                    self._write_gain_cell(*point, new)
                memory.update(updates)
                # Moving a fader invalidates a transient input-pair pan
                # reference; the next pan gesture reads live coefficients.
                balance_cache = getattr(self, '_input_pair_balance_cache', {})
                for key in list(balance_cache):
                    if key[0] == bus and any(col in key[1:] for col, _ in channels):
                        del balance_cache[key]
            except Exception as exc:
                memory.clear()
                memory.update(before_memory)
                failures = []
                for point, original in reversed(attempted):
                    try:
                        self._write_gain_cell(*point, original)
                    except Exception as rollback_error:
                        failures.append(str(rollback_error))
                if failures:
                    memory.clear()  # route history is no longer reliable
                    raise RuntimeError('Stereo fader write failed; rollback may be incomplete: '
                                       + '; '.join(failures)) from exc
                raise

    def write_stereo_level(self, bus, col, ui):
        """Backwards-compatible single mono strip entry point."""
        return self.write_stereo_levels(bus, [(col, 'mono')], ui)

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


    def _remember_router_source(self, destination, source):
        """Update the displayed mixer input when its hardware router changes.

        Router destinations define *which fader* is affected. Selected sources
        define the label beneath that fader. Never rename the underlying
        matrix channel or treat line-output routes as mixer-input routes.
        """
        if destination not in getattr(self, '_router_input_columns', {}):
            return
        if not hasattr(self, '_router_input_sources'):
            self._router_input_sources = {}
        value = str(source or '').strip()
        self._router_input_sources[destination] = (
            'Disconnected' if not value or value.startswith('Mute:') else value)

    def _resolved_matrix_inputs(self):
        """Display names in matrix-column order, without replacing FFADO IDs.

        The matrix column identifier is stable and is used for all gain writes.
        A DICE router may change the physical/FireWire source feeding that
        column at any moment; the display should use the same resolved source
        as the input strip, including FFADO's Mute:00 (Disconnected).
        """
        names = list(self.columns)
        for destination, col in getattr(self, '_router_input_columns', {}).items():
            source = getattr(self, '_router_input_sources', {}).get(destination)
            if source is not None and 0 <= col < len(names):
                names[col] = source
        return names

    def _refresh_router_input_sources(self):
        """Read only the available mixer-input destinations from FFADO.

        Called on matrix reads so the matrix also sees changes made by an
        external router application. A failed router read must not prevent
        adjusting matrix volumes. No routing or coefficients are written.
        """
        if not self.router_path or not getattr(self, '_router_input_columns', None):
            return
        try:
            destinations = set(map(str, self.helper.router_call(
                self.router_path, 'getDestinationNames')))
            updates = {}
            for destination in self._router_input_columns:
                if destination in destinations:
                    updates[destination] = str(self.helper.router_call(
                        self.router_path, 'getSourceForDestination', destination))
        except Exception:
            # Prefer a previously verified label over an unverified guess.
            return
        for destination, source in updates.items():
            self._remember_router_source(destination, source)

    @serialized_output
    def read_mix(self, mix, *, stereo_bus=False, channels=None):
        """Read a bus and (optionally) its linked right bus in one transaction.

        A linked bus derives its fader and balance from the *same* pair of
        native matrix coefficients. No coefficients are changed by a read.
        Optional channel IDs limit hardware reads to those visible strips.
        """
        if stereo_bus and (mix % 2 or mix + 1 >= len(self.mixes) or
                           self.matrix["mode"] not in ("dice_db", "rme_db")):
            raise ValueError("Stereo state requires a supported left output bus")
        if not 0 <= mix < len(self.mixes):
            raise ValueError("mix out of range")
        out = {}
        selected = set(channels) if channels is not None else None
        # Only the display label changes when a DICE input is re-routed.
        # Keep immutable matrix column indices, the names configuration, and
        # unrelated output routing exactly as they were.
        live_names = {index: self._router_input_sources[destination]
                      for destination, index in getattr(self, '_router_input_columns', {}).items()
                      if destination in getattr(self, '_router_input_sources', {})}
        for col in self._visible_cols():
            if selected is not None and f'ch/{col:02d}' not in selected:
                continue
            display_name = live_names.get(col, self.columns[col])
            entry = {"name": display_name, "input": display_name}
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
                    # The left coefficient was already read above to show the
                    # regular fader and check externally changed mute state.
                    # Reuse it *within this locked snapshot only*: reading it
                    # again doubled D-Bus calls without providing new state.
                    # The right leg must still be read live, including its
                    # independent software-mute/external-override checks.
                    left = float(self._matrix_raw(mix, col, actual=raw))
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
                    # Raw silence (-infinity or an unconnected route) is NOT
                    # necessarily a user mute. The button represents only the
                    # explicit software mute state; otherwise "unmute" appears
                    # clickable but has no original level to restore.
                    legs = (mix, mix + 1) if stereo_bus else (mix,)
                    muted = [(bus, col) in getattr(self, '_user_mutes', set()) for bus in legs]
                    entry["mute"] = all(muted)
                    entry["mute_partial"] = any(muted) and not all(muted)
                    entry["solo"] = all(col in getattr(self, '_solos', {}).get(bus, set()) for bus in legs)
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

    def write_group_mute(self, mixes, columns, value):
        """Mute an input pair and/or stereo bus as one verified operation.

        The FFADO DICE gain matrix has no per-cell hardware mute endpoint.
        Software mute therefore suppresses *each* affected input/bus route.
        An error restores every changed cell and its recovery journal before
        reporting failure. No new cross-routes are enabled by a mute.
        """
        self._write_group_mute_solo(mixes, columns, 'mute', value)

    def write_group_solo(self, mixes, columns, value):
        """Solo all selected inputs on every leg of a linked output bus.

        Set the entire input pair's logical state before changing gains, so
        one selected input is never silenced while enabling its partner.
        Every other input on the affected buses participates in rollback.
        """
        self._write_group_mute_solo(mixes, columns, 'solo', value)

    def _write_group_mute_solo(self, mixes, columns, control, value):
        if not self._soft_mute() or 'fader' not in self.roles:
            raise ValueError(f'Software matrix {control} is unavailable on this device')
        buses = tuple(dict.fromkeys(mixes))
        selected = tuple(dict.fromkeys(columns))
        if (not buses or not selected or
                any(type(bus) is not int or not 0 <= bus < len(self.mixes) for bus in buses) or
                any(type(col) is not int or not 0 <= col < len(self.columns) for col in selected)):
            raise ValueError(f'Invalid stereo {control} target')
        if type(value) is not bool:
            raise ValueError(f'{control.capitalize()} value must be true or false')
        affected = range(len(self.columns)) if control == 'solo' else selected
        targets = [(bus, col) for bus in buses for col in affected]
        with self.helper.transaction():
            self._require_recovery_resolved()
            if not hasattr(self, '_user_mutes'):
                self._user_mutes = set()
            if not hasattr(self, '_solos'):
                self._solos = {}
            path = self.roles['fader'][0]
            # Complete the external-edit checks before snapshotting any state.
            for key in targets:
                if key in self._matrix_mutes:
                    self._external_override(*key, self._get_cell(path, *key))
            before_raw = {key: self._get_cell(path, *key) for key in targets}
            before_saved = dict(self._matrix_mutes)
            before_mutes = set(self._user_mutes)
            before_solos = deepcopy(self._solos)
            try:
                if control == 'solo':
                    for bus in buses:
                        solos = self._solos.setdefault(bus, set())
                        if value:
                            solos.update(selected)
                        else:
                            solos.difference_update(selected)
                        if not solos:
                            self._solos.pop(bus, None)
                else:
                    for key in targets:
                        if value:
                            self._user_mutes.add(key)
                        else:
                            self._user_mutes.discard(key)
                for key in targets:
                    self._reconcile_cell(*key)
                # Re-read every target: the D-Bus call succeeding does not
                # guarantee that the device accepted the whole transaction.
                for key in targets:
                    actual = self._get_cell(path, *key)
                    if self._silenced(*key) and not self._is_zero(actual):
                        raise IOError(f'FFADO did not mute bus {key[0]+1}, input {key[1]+1}')
                    # If another solo or explicit user mute still suppresses
                    # this route, it must remain in the recovery journal.
                    if key in self._matrix_mutes and not self._silenced(*key):
                        raise IOError(f'FFADO did not restore bus {key[0]+1}, input {key[1]+1}')
                self._mute_fault = None
            except Exception as exc:
                self._user_mutes = before_mutes
                self._solos = before_solos
                failures = []
                # Unsilencing may already have removed saved levels. Journal
                # them again BEFORE rollback writes any of those cells to zero.
                self._matrix_mutes = {**before_saved, **self._matrix_mutes}
                journal_ready = True
                try:
                    self._save_soft_mutes()
                except Exception as journal_exc:
                    journal_ready = False
                    failures.append(f'recovery journal: {journal_exc}')
                for key, prior in before_raw.items():
                    try:
                        actual = self._get_cell(path, *key)
                        if not (self._is_zero(prior) and self._is_zero(actual)) and abs(float(actual) - float(prior)) > 0.000001:
                            if self._is_zero(prior) and not journal_ready:
                                raise RuntimeError('Cannot silence a rollback cell without a recovery journal')
                            self._set_cell(path, *key, prior)
                            self._verify_cell(*key, prior)
                    except Exception as rollback_exc:
                        failures.append(f'bus {key[0]+1}, input {key[1]+1}: {rollback_exc}')
                if not failures:
                    self._matrix_mutes = before_saved
                try:
                    self._save_soft_mutes()
                except Exception as journal_exc:
                    failures.append(f'recovery journal: {journal_exc}')
                # If rollback is incomplete, preserve the current journal;
                # never overwrite a possibly needed crash-recovery entry.
                self._mute_fault = f'Stereo {control} failed: {exc}'
                if failures:
                    self._mute_fault += '; incomplete rollback: ' + '; '.join(failures)
                raise RuntimeError(self._mute_fault) from exc

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
            self._write_group_mute_solo((mix,), (col,), control, value)
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
