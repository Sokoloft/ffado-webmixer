"""Per-device channel mute preferences, separate from crash recovery levels."""
from copy import deepcopy

from .mixer_outputs import serialized_output


class ChannelMuteControls:
    def _save_channel_mutes(self):
        if getattr(self, '_loading_channel_mutes', False):
            return
        states = ({key: True for key in self._user_mutes} if self._soft_mute()
                  else self._native_channel_mutes)
        snapshot = ({'schema': 1, **self._bus_gain_layout(),
                     'states': [{'mix': bus, 'column': col, 'mute': muted}
                                for (bus, col), muted in sorted(states.items())]}
                    if states else {})
        with self.config._save_lock:
            if snapshot == self.config.channel_mutes:
                return
            previous = self.config.channel_mutes
            self.config.channel_mutes = snapshot
            try:
                self.config.save()
            except Exception:
                self.config.channel_mutes = previous
                raise

    @serialized_output
    def load_channel_mutes(self):
        saved = deepcopy(self.config.channel_mutes)
        if not saved or any(saved[key] != value for key, value in self._bus_gain_layout().items()):
            return
        # An incomplete software mute transaction still needs explicit
        # recovery; preferences must never bypass its gain restoration guard.
        if self._pending_recovery or self._pending_output_recovery or getattr(self, '_recovery_corrupt', False):
            return
        self._loading_channel_mutes = True
        try:
            for item in saved['states']:
                self.write(item['mix'], f"ch/{item['column']:02d}", 'mute', item['mute'])
        finally:
            self._loading_channel_mutes = False

    @serialized_output
    def write_native_channel_mute(self, mix, col, value):
        path, spec = self.roles['mute']
        if not spec['writable']:
            raise ValueError('mute is read-only until a profile defines its range')
        if type(value) is not bool:
            raise ValueError('Mute value must be true or false')
        previous = self._get_cell(path, mix, col)
        saved = dict(self._native_channel_mutes)
        try:
            self._set_cell(path, mix, col, int(value))
            if bool(self._get_cell(path, mix, col)) != value:
                raise IOError('FFADO did not acknowledge channel mute change')
            self._native_channel_mutes[mix, col] = value
            self._save_channel_mutes()
        except Exception:
            self._native_channel_mutes = saved
            self._set_cell(path, mix, col, previous)
            if bool(self._get_cell(path, mix, col)) != bool(previous):
                raise RuntimeError('Channel mute rollback incomplete')
            raise
