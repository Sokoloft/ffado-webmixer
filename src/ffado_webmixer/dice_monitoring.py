"""Native Saffire DICE monitor controls, independent of matrix gain/mute.

Bindings follow FFADO's mixer/saffire_dice.py. UnActivate disables software
line monitoring, handing output level control to the front-panel knob;
DimLevel's 0..-87 range follows Saffire_Pro*_monitoring.ui.
"""
import math

from .profiles.capabilities import enabled
from .mixer_outputs import serialized_output


class DiceMonitoring:
    def dice_master_outputs(self):
        if self.profile.get('family') != 'saffire_dice':
            return ()
        return tuple(key for key, out in self.outputs.items()
                     if key.startswith('line/') and out.get('fader'))

    @serialized_output
    def read_dice_master(self):
        mute = self.dice_monitor_controls().get('mute')
        lines = self.dice_master_outputs()
        if not lines or not mute:
            raise ValueError('Global DICE Master is unavailable')
        states = [self.read_output(line) for line in lines]
        hardware = any(state.get('hardware_controlled') for state in states)
        return {'name': 'Master', 'level': None if hardware else max(s['level'] for s in states),
                'hardware_controlled': hardware,
                'mute': bool(self._read_scalar(mute['state'])), 'emulated_mute': False}

    @serialized_output
    def write_dice_master(self, control, value):
        mute = self.dice_monitor_controls().get('mute')
        if not self.dice_master_outputs() or not mute:
            raise ValueError('Global DICE Master is unavailable')
        if control == 'mute' and type(value) is bool:
            self._monitor_changes([(mute['state'], value)] +
                                  [(item, True) for item in mute['members']])
        elif control == 'fader':
            return self.write_linked_output('dice/master', control, value)
        else:
            raise ValueError('Invalid DICE Master control or value')

    def dice_monitor_controls(self):
        if self.profile.get('family') != 'saffire_dice':
            return {}
        features = self.profile.get('capabilities', {}).get('features', {})
        controls = {c['path']: c for c in self.device.get('controls', [])}
        base = self.device['device'] + '/EAP/Monitoring/'

        def control(suffix, kind):
            item = controls.get(base + suffix)
            return item if item and item['kind'] == kind else None

        def lines(feature, role):
            if not enabled(self.profile, feature):
                return []
            count = int(features[feature].get('extra_count', 0))
            result = [control(f'LineOut/{role}{n}', 'Boolean') for n in range(1, count + 1)]
            return result if result and all(result) else []

        result = {}
        for key, feature, suffix, role in (
                ('dim', 'monitor_global_dim', 'GlobalDim/State', 'GDim'),
                ('mute', 'monitor_global_mute', 'GlobalMute/State', 'GMute')):
            state = control(suffix, 'Boolean') if enabled(self.profile, feature) else None
            members = lines(feature, role)
            level = control('GlobalDim/Level', 'Discrete') if key == 'dim' else None
            if state and members and (key != 'dim' or level):
                result[key] = {'state': state, 'members': members, 'level': level}
        hardware = lines('monitor_line_volume', 'UnActivate')
        if hardware:
            result['hw_monitor'] = hardware
        return result

    def dice_monitor_description(self):
        return {key: True for key in self.dice_monitor_controls()}

    def _monitor_changes(self, changes):
        """Verify every write and restore attempted changes after any failure."""
        before = [(control, self._read_scalar(control)) for control, _ in changes]
        attempted = []
        try:
            for (control, value), (_, original) in zip(changes, before):
                attempted.append((control, original))
                self._write_scalar(control, value)
                if self._read_scalar(control) != value:
                    raise IOError('FFADO did not acknowledge DICE monitor change')
        except Exception as exc:
            failed = []
            for control, original in reversed(attempted):
                try:
                    self._write_scalar(control, original)
                    if self._read_scalar(control) != original:
                        raise IOError('readback mismatch')
                except Exception as rollback_exc:
                    failed.append(str(rollback_exc))
            if failed:
                raise RuntimeError('DICE monitor change failed; rollback may be incomplete: '
                                   + '; '.join(failed)) from exc
            raise

    def dice_line_hardware_controlled(self, out_id):
        if not out_id.startswith('line/'):
            return False
        controls = self.dice_monitor_controls().get('hw_monitor', [])
        index = int(out_id.split('/')[1]) - 1
        return bool(controls and 0 <= index < len(controls) and
                    self._read_scalar(controls[index]))

    @serialized_output
    def read_dice_monitoring(self):
        controls = self.dice_monitor_controls()
        result = self.dice_monitor_description()
        hardware = controls.get('hw_monitor')
        if hardware:
            states = [bool(self._read_scalar(item)) for item in hardware]
            result['hw_monitor'] = all(states)
            result['hw_monitor_partial'] = any(states) and not all(states)
        return result

    @serialized_output
    def write_dice_monitoring(self, control, value):
        if control != 'hw_monitor' or type(value) is not bool:
            raise ValueError('Expected boolean hw_monitor')
        controls = self.dice_monitor_controls().get('hw_monitor')
        if not controls:
            raise ValueError('Hardware monitoring is not supported on this device')
        # UnActivate bypasses software line monitoring so the knob controls gain.
        # Preserve per-line levels and mutes; do not estimate the knob's gain.
        self._monitor_changes([(item, value) for item in controls])
        return self.read_dice_monitoring()

    @serialized_output
    def read_dice_dim(self):
        controls = self.dice_monitor_controls()
        dim, mute = controls.get('dim'), controls.get('mute')
        if not dim or not mute:
            raise ValueError('Global DICE Dim and hardware mute are unavailable')
        active = bool(self._read_scalar(dim['state']))
        raw = self._read_scalar(dim['level'])
        if not math.isfinite(float(raw)) or not -87 <= raw <= 0:
            raise IOError('Invalid DICE Dim level')
        # Reserve position zero for Off. Positions 1..88 run from -87 to 0 dB.
        return {'name': 'Dim', 'level': (float(raw) + 88) * 100 / 88,
                'mute': not active,
                'dim_active': active, 'emulated_mute': False}

    @serialized_output
    def write_dice_dim(self, control, value):
        controls = self.dice_monitor_controls()
        dim, mute = controls.get('dim'), controls.get('mute')
        if not dim or not mute:
            raise ValueError('Global DICE Dim and hardware mute are unavailable')
        if control == 'mute' and type(value) is bool:
            changes = [(dim['state'], not value)] + [(item, True) for item in dim['members']]
        elif (control == 'fader' and not isinstance(value, bool) and isinstance(value, (int, float))
              and math.isfinite(value) and 0 <= value <= 100):
            active = value > 0
            raw = max(1, round(value * 88 / 100)) - 88 if active else 0
            # Disable first when returning to Off; enable only after setting
            # the requested finite level when leaving Off.
            changes = ([(dim['level'], raw), (dim['state'], True)] if active else
                       [(dim['state'], False), (dim['level'], 0)])
            changes += [(item, True) for item in dim['members']]
        else:
            raise ValueError('Invalid DICE Dim control or value')
        self._monitor_changes(changes)
