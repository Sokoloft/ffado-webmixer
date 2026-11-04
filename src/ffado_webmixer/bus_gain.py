"""Persistent bus gain over DICE matrix coefficients, independent of line outputs.

Keep unscaled coefficients while sending scaled values to FFADO. Resume matching
hardware without applying gain twice; journal incomplete hardware transactions.
"""
from copy import deepcopy
import math

from .gain import UNITY, NATIVE_LIMITS, ui_to_raw
from .mixer_outputs import serialized_output


class BusGainControls:
    def _bus_gain_layout(self):
        # Routing annotations may change after discovery. The fixed matrix
        # endpoint names and dimensions identify the bus/column coordinates.
        return {'guid': self.guid.lower(), 'matrix_path': self.roles['fader'][0],
                'columns': [str(name).split('\n', 1)[0] for name in self.columns],
                'mixes': [str(name).split('\n', 1)[0] for name in self.mixes]}

    def _save_bus_gains(self):
        if not self.has_bus_gain() or getattr(self, '_loading_bus_gains', False):
            return
        states = getattr(self, '_bus_gains', {})
        if not states and not getattr(self.config, 'bus_gains', {}):
            return
        snapshot = ({'schema': 1, **self._bus_gain_layout(),
                     'buses': {str(bus): {'level': state['level'], 'mute': state['mute'],
                                          'cells': [state['cells'][col] for col in range(len(self.columns))]}
                               for bus, state in states.items()}}
                    if states else {})
        with self.config._save_lock:
            if snapshot == self.config.bus_gains:
                return
            old = self.config.bus_gains
            self.config.bus_gains = snapshot
            try:
                self.config.save()
            except Exception:
                self.config.bus_gains = old
                raise

    def _commit_bus_gains(self):
        if getattr(self, '_loading_bus_gains', False):
            return
        self._save_bus_gains()
        if self._recovery_journal:
            # Fully saved bus gain no longer needs mute recovery. Independent
            # channel mute/solo and incomplete writes retain their journal.
            self._recovery_journal.write({**self._matrix_mutes, **self._pending_recovery})

    @serialized_output
    def load_bus_gains(self):
        saved = deepcopy(self.config.bus_gains)
        if not saved or not self.has_bus_gain() or getattr(self, '_recovery_corrupt', False):
            return
        if any(saved[key] != value for key, value in self._bus_gain_layout().items()):
            return  # A different device or matrix cannot reuse these baselines.
        path = self.roles['fader'][0]
        reapply = []
        for key, item in saved['buses'].items():
            bus = int(key)
            state = {**item, 'cells': dict(enumerate(item['cells']))}
            actual = [self.helper.get_cell(path, *self._coordinates(bus, col))
                      for col in range(len(self.columns))]
            expected = [self._bus_scaled(state['cells'][col], state) for col in range(len(self.columns))]
            if all((self._is_zero(raw) and self._is_zero(want)) or abs(raw - want) <= 1
                   for raw, want in zip(actual, expected)):
                self._bus_gains[bus] = state
                for col, base in state['cells'].items():
                    if self._pending_recovery.get((bus, col)) == base:
                        self._pending_recovery.pop((bus, col))
            else:
                reapply.append((bus, item))
        if self._pending_recovery or self._pending_output_recovery:
            return  # An interrupted independent mute still requires recovery.
        self._loading_bus_gains = True
        try:
            for bus, item in reapply:
                # Keep baselines for unchanged cells; only changed/reset
                # coefficients become new baselines. Never scale an already
                # scaled, unchanged route a second time.
                live = {}
                for col, base in enumerate(item['cells']):
                    raw = self.helper.get_cell(path, *self._coordinates(bus, col))
                    expected = self._bus_scaled(base, item)
                    matches = (self._is_zero(raw) and self._is_zero(expected)) or abs(raw - expected) <= 1
                    live[col] = base if matches else raw
                # Restore gain and mute in one transaction, without briefly
                # writing an unmuted mix when the saved bus was muted.
                self.write_bus_gain(f'bus/{bus}', 'fader', item['level'], linked=False,
                                    restore_mute=item['mute'], restore_cells=live)
        finally:
            self._loading_bus_gains = False
        self._commit_bus_gains()

    def has_bus_gain(self):
        return (self.matrix.get('mode') == 'dice_db' and
                self.roles.get('fader', (None, {}))[1].get('writable', False))

    def is_bus_gain_output(self, out_id):
        return self.has_bus_gain() and out_id in self.outputs and out_id.startswith('bus/')

    def _bus_gain_state(self, mix):
        return getattr(self, '_bus_gains', {}).get(mix)

    def _bus_factor(self, state):
        return 0 if state['mute'] else ui_to_raw(state['level'], 'dice_db') / UNITY

    def _bus_scaled(self, raw, state):
        if not math.isfinite(float(raw)) or not 0 <= float(raw) <= NATIVE_LIMITS['dice_db']:
            raise ValueError('Invalid native bus coefficient from FFADO')
        value = 0 if self._is_zero(raw) else round(float(raw) * self._bus_factor(state))
        if value > NATIVE_LIMITS['dice_db']:
            raise ValueError('Bus gain exceeds the hardware coefficient range; lower the bus or channel gain')
        return value

    def _bus_read_cell(self, mix, col, actual):
        state = self._bus_gain_state(mix)
        if state is None:
            return actual
        expected = self._bus_scaled(state['cells'][col], state)
        if ((self._is_zero(actual) and self._is_zero(expected)) or
                abs(float(actual) - expected) <= 1):
            return state['cells'][col]
        # An external edit invalidates the bus multiplier. Adopt the actual
        # matrix without writing anything, including when gain was at silence.
        del self._bus_gains[mix]
        self._save_soft_mutes()
        self._mute_fault = f'External matrix change on bus {mix + 1}; bus gain reset to 0 dB.'
        return actual

    @serialized_output
    def read_bus_gain(self, out_id):
        mix = self.outputs[out_id]['mix']
        # Reconcile all cells before exposing a session master value.
        for col in range(len(self.columns)):
            self._get_cell(self.roles['fader'][0], mix, col)
        state = self._bus_gain_state(mix)
        return {'name': self.config.names.get('bus:' + str(mix), self.outputs[out_id]['name']),
                'level': state['level'] if state else 100 * 60 / 66,
                'mute': state['mute'] if state else False, 'emulated_mute': True,
                'software_bus_gain': True}

    @serialized_output
    def write_bus_gain(self, out_id, control, value, *, linked=True, restore_mute=None, restore_cells=None):
        if control == 'mute':
            if type(value) is not bool:
                raise ValueError('Bus mute must be a boolean')
        elif control == 'fader':
            if (type(value) not in (int, float) or not math.isfinite(value) or
                    not 0 <= value <= 100):
                raise ValueError('Bus level must be between 0 and 100')
        else:
            raise ValueError('Unknown bus gain control')
        if restore_mute is not None and type(restore_mute) is not bool:
            raise ValueError('Invalid saved bus mute')
        self._require_recovery_resolved()
        pair = self.linked_outputs(out_id) if linked else (out_id,)
        buses = [self.outputs[channel]['mix'] for channel in pair]
        path = self.roles['fader'][0]
        # Finish external-edit reconciliation before taking the snapshot.
        for channel in pair:
            self.read_bus_gain(channel)
        old = deepcopy(self._bus_gains)
        native = {(bus, col): self.helper.get_cell(path, *self._coordinates(bus, col))
                  for bus in buses for col in range(len(self.columns))}
        states = {}
        for bus in buses:
            state = deepcopy(self._bus_gain_state(bus))
            if state is None:
                state = {'level': 100 * 60 / 66, 'mute': False,
                         'cells': {col: native[bus, col] for col in range(len(self.columns))}}
            if restore_cells is not None:
                state['cells'] = dict(restore_cells)
            state['level' if control == 'fader' else 'mute'] = value
            if restore_mute is not None:
                state['mute'] = restore_mute
            states[bus] = state
        # Preflight every coefficient, including both stereo legs, before writes.
        changes = {(bus, col): self._bus_scaled(raw, state)
                   for bus, state in states.items() for col, raw in state['cells'].items()}
        self._bus_gains.update(states)
        attempted = []
        try:
            self._save_soft_mutes()
            for (bus, col), raw in changes.items():
                attempted.append((bus, col))
                self._set_native_cell(path, bus, col, raw)
            self._commit_bus_gains()
        except Exception as exc:
            failures = []
            for bus, col in reversed(attempted):
                try:
                    self._set_native_cell(path, bus, col, native[bus, col])
                except Exception as rollback_exc:
                    failures.append(str(rollback_exc))
            self._bus_gains = old
            if failures:
                # Keep recovery targets and block further edits after an
                # incomplete rollback. Recovery never runs automatically.
                for bus in buses:
                    self._bus_gains.pop(bus, None)
                    for col, raw in states[bus]['cells'].items():
                        self._pending_recovery[bus, col] = self._matrix_mutes.get((bus, col), raw)
            self._save_soft_mutes()
            if failures:
                raise RuntimeError('Bus gain failed; rollback incomplete: ' + '; '.join(failures)) from exc
            raise

    def _bus_recovery_levels(self):
        return {(bus, col): raw for bus, state in self._bus_gains.items()
                for col, raw in state['cells'].items()
                if self._bus_scaled(raw, state) != raw}
