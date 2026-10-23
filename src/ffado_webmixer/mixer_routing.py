"""Matrix and source-routing operations for the profile-driven Mixer.

These controls use the Mixer's resolved topology and hardware transaction helper.
Gain writes go through the shared recovery guards on Mixer, so routing edits and
strip edits preserve the same mute recovery and external-change behavior.
"""
import math

from .gain import has_db_scale, scale as gain_scale, raw_to_db, db_to_raw
from .profile_loader import destination_options, resolve_phones_assignment
from .profiles.capabilities import enabled


class RoutingControls:
    """Matrix editing, stereo playback routing and device destination controls."""

    # ---------- matrix and crossbar router API ----------
    def _matrix_raw(self, mix, col, *, actual=None):
        """Read effective gain, respecting external hardware changes.

        ``actual`` is an optional live coefficient *already read inside the
        same hardware transaction*. It is never cached between requests or
        shared with another bus/column. The existing external-override guard
        must run even when a caller supplies that coefficient.
        """
        key = (mix, col)
        if actual is None:
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
        # The matrix editor must use the same live input-source labels as
        # the fader strips. Keep `inputs` immutable for existing clients;
        # `input_labels` is presentation-only and indexes the same columns.
        with self.helper.transaction():
            self._refresh_router_input_sources()
            display_inputs = self._resolved_matrix_inputs()
        data = {"inputs": self.columns, "input_labels": display_inputs,
                "outputs": self.mixes, "values": values,
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

    def stereo_firewire_options(self):
        """Discover *live* DAW/FireWire playback pairs on DICE's EAP router.

        Audio from JACK's left/right playback ports enters the device as two
        separate 1394/In sources. Those are assigned to Mixer/In destinations
        before the 18x16 monitoring matrix. Never assume 1394 1/2 occupy
        mixer columns 1/2: assignments can be changed by the Crossbar Router.
        """
        if (not self.router_path or self.matrix.get('mode') != 'dice_db' or
                'fader' not in self.roles or not self.roles['fader'][1].get('writable')):
            return {'available': False, 'pairs': [], 'buses': []}
        import re
        with self.helper.transaction():
            sources = set(map(str, self.helper.router_call(self.router_path, 'getSourceNames')))
            destinations = set(map(str, self.helper.router_call(self.router_path, 'getDestinationNames')))
            assigned = {}
            for dest, col in self._router_input_columns.items():
                if dest in destinations:
                    source = str(self.helper.router_call(self.router_path, 'getSourceForDestination', dest))
                    self._remember_router_source(dest, source)
                    assigned.setdefault(source, []).append((dest, col))
            pairs = []
            for source in sorted(sources):
                match = re.fullmatch(r'1394/In:(\d+)', source)
                if not match or int(match.group(1)) % 2 == 0:
                    continue
                number = int(match.group(1))
                right_name = f'1394/In:{number+1:02d}'
                if right_name not in sources:
                    continue
                left_cols, right_cols = assigned.get(source, []), assigned.get(right_name, [])
                # If either source is absent or duplicated, choosing a mixer
                # channel would be ambiguous. Do not silently guess.
                if len(left_cols) != 1 or len(right_cols) != 1:
                    continue
                _, left_col = left_cols[0]
                _, right_col = right_cols[0]
                if left_col == right_col:
                    continue
                pairs.append({'left_source': source, 'right_source': right_name,
                              'left_input': left_col, 'right_input': right_col,
                              'label': f'Firewire {number}+{number+1}'})
        return {'available': bool(pairs), 'pairs': pairs,
                'buses': [{'left': bus, 'label': f'Bus {bus+1}+{bus+2}'}
                          for bus in range(0, len(self.mixes)-1, 2)]}

    def stereo_firewire_apply(self, left_source, bus):
        """Explicitly patch a DAW stereo pair onto one stereo output bus pair.

        At unity, only (L input -> L bus) and (R input -> R bus) are on.
        The *other two* crosspoints are silent so this does not collapse a
        stereo recording into mono. All unrelated cells and router assignments
        stay untouched. Unlike pressing Link, this deliberately changes mixer
        levels; a failed D-Bus write is followed by best-effort rollback.
        """
        if type(bus) is not int or bus < 0 or bus % 2 or bus + 1 >= len(self.mixes):
            raise ValueError('Select a valid stereo output bus pair')
        if not isinstance(left_source, str):
            raise ValueError('Select a FireWire playback pair')
        with self.helper.transaction():
            options = self.stereo_firewire_options()
            selected = next((pair for pair in options['pairs']
                             if pair['left_source'] == left_source), None)
            if selected is None:
                raise ValueError('FireWire playback pair is not uniquely assigned to two mixer inputs')
            self._require_recovery_resolved()
            left_col, right_col = selected['left_input'], selected['right_input']
            points = [(bus, left_col), (bus+1, right_col),
                      (bus, right_col), (bus+1, left_col)]
            if any(point in self._matrix_mutes or point in self._user_mutes
                   for point in points):
                raise ValueError('Unmute the affected stereo inputs before setting playback routing')
            before = {point: self._matrix_raw(*point) for point in points}
            unity = db_to_raw(0, self.matrix['mode'])
            targets = [unity, unity, 0, 0]
            attempted = []
            try:
                for point, target in zip(points, targets):
                    if before[point] != target:
                        attempted.append(point)
                        self._write_gain_cell(*point, target)
                        # Some helper implementations do not read back writes;
                        # verify the real device value before reporting success.
                        actual = self._matrix_raw(*point)
                        if actual != target:
                            raise IOError(f'FFADO readback differs at mixer cell {point}')
            except Exception as exc:
                failures = []
                for point in reversed(attempted):
                    try:
                        self._write_gain_cell(*point, before[point])
                    except Exception as rollback_exc:
                        failures.append(str(rollback_exc))
                if failures:
                    raise RuntimeError('Stereo playback routing failed; rollback may be incomplete: '
                                       + '; '.join(failures)) from exc
                raise
            # Rebuild balance from actual matrix data on the next read.
            cache = getattr(self, '_input_pair_balance_cache', {})
            for key in list(cache):
                if key[0] == bus and (left_col in key[1:] or right_col in key[1:]):
                    del cache[key]
            return {'ok': True, 'bus': bus, 'left_input': left_col,
                    'right_input': right_col, 'pair': selected['label'],
                    'routes': [dict(bus=point[0], input=point[1], native=self._matrix_raw(*point))
                               for point in points]}

    def router_snapshot(self):
        if not self.router_path:
            raise ValueError("No FFADO crossbar router exposed for this device")
        path = self.router_path
        with self.helper.transaction():
            sources = [str(x) for x in self.helper.router_call(path, "getSourceNames")]
            destinations = [str(x) for x in self.helper.router_call(path, "getDestinationNames")]
            selected = {d: str(self.helper.router_call(path, "getSourceForDestination", d))
                        for d in destinations}
            # Opening/refreshing the Crossbar Router also synchronizes labels
            # with edits made in ffado-mixer or another controller.
            for destination, source in selected.items():
                self._remember_router_source(destination, source)
        return {"sources": sources, "destinations": destinations, "selected": selected}

    def router_set(self, destination, source):
        if not self.router_path:
            raise ValueError("No FFADO crossbar router exposed")
        path = self.router_path
        with self.helper.transaction():
            sources = [str(x) for x in self.helper.router_call(path, "getSourceNames")]
            destinations = [str(x) for x in self.helper.router_call(path, "getDestinationNames")]
            if (source and source not in sources) or destination not in destinations:
                raise ValueError("Source or destination is not available")
            before = str(self.helper.router_call(path, "getSourceForDestination", destination))
            if before == source or (not source and before.startswith('Mute:')):
                self._remember_router_source(destination, before)
                return

            def selected():
                return str(self.helper.router_call(path, "getSourceForDestination", destination))

            def connect(name, enabled):
                if not self.helper.router_call(path, "setConnectionState", name, destination, enabled):
                    raise ValueError(f"FFADO refused to {'connect' if enabled else 'disconnect'} {name}")

            try:
                # FFADO's OutputSwitcher disconnects the old source first.
                # Both operations may raise *after* modifying the device, so
                # recovery must inspect hardware, not just the return value.
                if before and not before.startswith('Mute:'):
                    connect(before, False)
                if source:
                    connect(source, True)
                actual = selected()
                if not (actual == source or (not source and actual.startswith('Mute:'))):
                    raise IOError('FFADO routing readback did not match the requested connection')
            except Exception as exc:
                # Restore the previous source (or a muted destination) on any
                # failure, including a thrown D-Bus exception or bad readback.
                # Never try to *connect* the synthetic Mute:00 source.
                try:
                    actual = selected()
                    if actual != before and not (actual.startswith('Mute:') and before.startswith('Mute:')):
                        if actual and not actual.startswith('Mute:'):
                            connect(actual, False)
                        if before and not before.startswith('Mute:'):
                            connect(before, True)
                    restored = selected()
                    if restored != before and not (restored.startswith('Mute:') and before.startswith('Mute:')):
                        raise IOError(f'expected {before!r}, got {restored!r}')
                except Exception as rollback_exc:
                    raise RuntimeError('FFADO routing failed; rollback may be incomplete: '
                                       + str(rollback_exc)) from exc
                self._remember_router_source(destination, restored)
                raise
            # Cache only verified hardware selections, including Mute:00.
            self._remember_router_source(destination, actual)

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
