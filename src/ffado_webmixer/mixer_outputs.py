"""Master-output levels and persistent software mute for the Mixer.

Output read/modify/write operations share the Mixer's hardware transaction and
configuration, including pending recovery and externally adjusted levels.
"""
from functools import wraps
import math


def serialized_output(method):
    """Keep output mute read/modify/write sequences atomic across API threads."""
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self.helper.transaction():
            return method(self, *args, **kwargs)
    return wrapper


class OutputControls:
    """Main, Phones and bus output levels with verified mute transitions."""

    def output_pairs(self):
        """Only source-mapped DICE line controls can form physical pairs."""
        if self.matrix.get('mode') != 'dice_db':
            return []
        pairs = []
        for out_id, output in self.outputs.items():
            if not out_id.startswith('line/'):
                continue
            number = int(out_id.split('/')[1])
            right = self.outputs.get(f'line/{number + 1}')
            if number % 2 and output.get('fader') and right and right.get('fader'):
                pairs.append([out_id, right['id']])
        return pairs

    def linked_outputs(self, out_id):
        if self.is_bus_gain_output(out_id):
            mix = self.outputs[out_id]['mix']
            left = mix - mix % 2
            if left in self.config.settings.get('stereo_buses', []) and left + 1 < len(self.mixes):
                return (f'bus/{left}', f'bus/{left + 1}')
        for left, right in self.output_pairs():
            if left in self.config.settings.get('stereo_outputs', []) and out_id in (left, right):
                return (left, right)
        return (out_id,)

    @serialized_output
    def read_linked_output(self, out_id):
        pair = self.linked_outputs(out_id)
        states = [self.read_output(channel) for channel in pair]
        result = dict(states[0])
        if len(pair) == 2:
            result.update(level=(None if any(state['level'] is None for state in states)
                                 else max(state['level'] for state in states)),
                          mute=all(state['mute'] for state in states),
                          hardware_controlled=any(state.get('hardware_controlled') for state in states),
                          partner=pair[1])
        return result

    @serialized_output
    def write_linked_output(self, out_id, control, value):
        if self.is_bus_gain_output(out_id):
            return self.write_bus_gain(out_id, control, value)
        pair = self.linked_outputs(out_id)
        if control == 'mute':
            if type(value) is not bool:
                raise ValueError('Output mute must be a boolean')
        elif control == 'fader':
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                    not math.isfinite(value) or not 0 <= value <= 100):
                raise ValueError('Output level must be between 0 and 100')
        else:
            raise ValueError('Unknown output control')
        # Validate both legs before changing either one.
        for channel in pair:
            output = self._output(channel)
            if control == 'fader' and self.dice_line_hardware_controlled(channel):
                raise ValueError('Output level is controlled by the hardware monitor knob')
            if not output.get('spec', self.out_spec)['writable']:
                raise ValueError('Output level is read-only')
            if channel in getattr(self, '_pending_output_recovery', set()):
                raise RuntimeError('This output has a pending mute recovery')
        if len(pair) == 1:
            return self.write_output(out_id, control, value)
        before = {channel: self.read_output(channel) for channel in pair}
        attempted = []
        try:
            for channel in pair:
                attempted.append(channel)
                self.write_output(channel, control, value)
        except Exception as exc:
            errors = []
            for channel in reversed(attempted):
                try:
                    self.write_output(channel, control, before[channel]['level' if control == 'fader' else 'mute'])
                except Exception as rollback_exc:
                    errors.append(f'{channel}: {rollback_exc}')
            if errors:
                raise RuntimeError('Linked output change failed; rollback may be incomplete: '
                                   + '; '.join(errors)) from exc
            raise

    # ---------- output (master) faders: Main, Phones, buses ----------
    def _output(self, out_id):
        out = self.outputs.get(out_id)
        if out is None or out["fader"] is None:
            raise ValueError(f"'{out_id}' has no level control on this device")
        return out

    def _save_mute_memory(self):
        self.config.save()

    @serialized_output
    def load_bus_mutes(self):
        """Recall native bus mutes after the GUID-specific config is attached."""
        for out_id, muted in self.config.bus_mutes.items():
            out = self.outputs.get(out_id)
            if (out is None or not out.get('fader') or not out.get('mute')
                    or self.is_bus_gain_output(out_id)):
                continue
            if bool(self._read_scalar(out['mute'])) != muted:
                self._write_scalar(out['mute'], muted)
                if bool(self._read_scalar(out['mute'])) != muted:
                    raise IOError('FFADO did not acknowledge saved bus mute')

    def _verify_output(self, out, expected):
        fader = out['fader']
        actual = self.helper.get_value(fader['path'], fader['kind'])
        if not math.isfinite(float(actual)) or abs(float(actual) - float(expected)) > 0.00001:
            raise IOError(f'FFADO rejected output level for {out["name"]}: '
                          f'expected {expected}, received {actual}')
        return actual

    @serialized_output
    def read_output(self, out_id):
        if self.is_bus_gain_output(out_id):
            return self.read_bus_gain(out_id)
        if out_id == 'dice/dim':
            return self.read_dice_dim()
        out = self._output(out_id)
        if self.dice_line_hardware_controlled(out_id):
            return {'name': out['name'], 'level': None, 'hardware_controlled': True,
                    'mute': bool(self._read_scalar(out['mute'])) if out['mute'] else False,
                    'emulated_mute': False}
        raw = self.helper.get_value(out["fader"]["path"], out["fader"]["kind"])
        spec = out.get("spec", self.out_spec)
        lo = spec.get("min", 0)

        def norm(value):
            return self._to_ui(value, spec) if spec["writable"] else 0

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
        if self.is_bus_gain_output(out_id):
            return self.write_bus_gain(out_id, control, value, linked=False)
        if out_id == 'dice/dim':
            return self.write_dice_dim(control, value)
        if control == 'fader' and self.dice_line_hardware_controlled(out_id):
            raise ValueError('Output level is controlled by the hardware monitor knob')
        out = self._output(out_id)
        spec = out.get("spec", self.out_spec)
        if not spec["writable"]:
            raise ValueError("output level is read-only until a profile defines its range")
        fader = out["fader"]
        lo = spec["min"]
        emulated = out["mute"] is None

        if emulated and getattr(self, '_pending_output_recovery', set()) and out_id in self._pending_output_recovery:
            raise RuntimeError('This output has a pending mute recovery. Restore or keep current levels first.')
        if control == "fader":
            raw = self._from_ui(value, spec)
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
            previous = bool(self._read_scalar(out['mute']))
            self._write_scalar(out["mute"], bool(value))
            if bool(self._read_scalar(out["mute"])) != bool(value):
                raise IOError('FFADO did not acknowledge output mute change')
            if out_id.startswith('bus/'):
                with self.config._save_lock:
                    saved = dict(self.config.bus_mutes)
                    self.config.bus_mutes[out_id] = bool(value)
                    try:
                        self.config.save()
                    except Exception:
                        self.config.bus_mutes.clear()
                        self.config.bus_mutes.update(saved)
                        self._write_scalar(out['mute'], previous)
                        if bool(self._read_scalar(out['mute'])) != previous:
                            raise RuntimeError('Saving bus mute failed; hardware rollback incomplete')
                        raise
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
