from flask import jsonify, request
from contextlib import nullcontext
import queue
from ..services.peak_stream import PeakStreamHub
from ..services.stereo import MIRRORED, pair_name
from ..mixer import input_pair_balance_from_raw

def write_linked_controls(backend, mix, pair, control, value):
    """Write a visible linked strip with best-effort rollback on any failure.

    Snapshot the UI control values *before* touching either channel. A missing
    hardware control (e.g. gain on just one input) remains optional, as before,
    but no write is attempted without a value available for restoration.
    On FFADO hardware, hold its transaction lock across snapshot and writes so
    concurrent browser requests cannot interleave the two legs.
    """
    helper = getattr(backend, 'helper', None)
    transaction = helper.transaction() if helper is not None else nullcontext()
    with transaction:
        state = backend.read_mix(mix)
        if any(channel not in state for channel in pair):
            raise ValueError('One or both linked channels are unavailable')
        originals = {channel: state[channel][control] for channel in pair
                     if control in state[channel] and state[channel][control] is not None}
        if not originals:
            raise ValueError(f'Neither linked channel supports {control}')
        attempted = []
        try:
            for channel in pair:
                if channel in originals:
                    # Include a call which raises: a D-Bus write may have
                    # reached the device before reporting an error.
                    attempted.append(channel)
                    backend.write(mix, channel, control, value)
        except Exception as exc:
            failed = []
            for channel in reversed(attempted):
                try:
                    backend.write(mix, channel, control, originals[channel])
                except Exception as rollback_exc:
                    failed.append(f'{channel}: {rollback_exc}')
            if failed:
                raise RuntimeError('Linked-channel write failed; rollback may be incomplete: '
                                   + '; '.join(failed)) from exc
            raise


def register(app, backend, description, config, broadcast):
    peak_streams = PeakStreamHub()
    @app.get("/api/describe")
    def describe():
        # Output names (Main, Phones, buses) can be renamed in the UI; saved names win.
        result = dict(backend.describe())
        result['stereo_buses'] = config.settings.get('stereo_buses', [])
        result['stereo_bus_names'] = {str(left): config.names['bus-pair:' + str(left)]
                                      for left in result['stereo_buses']
                                      if 'bus-pair:' + str(left) in config.names}
        result['mixes'] = [dict(mix, name=config.names.get('bus:' + str(mix['id']), mix['name']))
                           for mix in result.get('mixes', [])]
        result["outputs"] = [
            dict(output, base_name=output["name"], name=config.names.get("out:" + output["id"], output["name"]))
            for output in result.get("outputs", [])
        ]

        return jsonify(result)

    @app.post('/api/bus-name')
    def rename_bus():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error='Bus rename must be an object'), 400
        mix, name = payload.get('mix'), payload.get('name')
        if type(mix) is not int or not 0 <= mix < len(backend.mixes):
            return jsonify(error='Unknown bus'), 400
        if not isinstance(name, str) or not 0 < len(name.strip()) <= 16:
            return jsonify(error='Bus name must contain 1 to 16 characters'), 400
        key = 'bus:' + str(mix)
        with config._save_lock:
            previous = config.names.get(key)
            config.names[key] = name.strip()
            try:
                config.save()
            except Exception as exc:
                if previous is None:
                    config.names.pop(key, None)
                else:
                    config.names[key] = previous
                try:
                    config.save()
                except Exception:
                    return jsonify(error='Could not save bus name; rollback may be incomplete'), 500
                return jsonify(error='Could not save bus name: ' + str(exc)), 500
        broadcast({'type':'bus-name', 'mix':mix, 'name':name.strip()})
        return jsonify(ok=True)

    @app.post('/api/bus-pair-name')
    def rename_bus_pair():
        """An alias is for the *linked tab*, never either underlying FFADO bus."""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error='Linked bus rename must be an object'), 400
        left, name = payload.get('left'), payload.get('name')
        if type(left) is not int or left < 0 or left % 2 or left + 1 >= len(backend.mixes):
            return jsonify(error='Unknown consecutive bus pair'), 400
        if not isinstance(name, str) or not 0 < len(name.strip()) <= 32:
            return jsonify(error='Linked bus name must contain 1 to 32 characters'), 400
        key = 'bus-pair:' + str(left)
        with config._save_lock:
            if left not in config.settings.get('stereo_buses', []):
                return jsonify(error='The pair is not linked'), 400
            previous = config.names.get(key)
            config.names[key] = name.strip()
            try:
                config.save()
            except Exception as exc:
                if previous is None:
                    config.names.pop(key, None)
                else:
                    config.names[key] = previous
                try:
                    config.save()
                except Exception:
                    return jsonify(error='Linked bus rename failed; rollback may be incomplete'), 500
                return jsonify(error='Could not save linked bus name: ' + str(exc)), 500
        broadcast({'type': 'bus-pair-name', 'left': left, 'name': name.strip()})
        return jsonify(ok=True)

    @app.get('/api/mute-recovery')
    def mute_recovery_status():
        if not hasattr(backend, 'mute_recovery_status'):
            return jsonify(pending=0, channels=[], fault=None)
        return jsonify(backend.mute_recovery_status())

    @app.post('/api/mute-recovery')
    def mute_recovery_action():
        if not hasattr(backend, 'resolve_mute_recovery'):
            return jsonify(error='This device has no software-mute recovery'), 400
        try:
            action = (request.get_json(force=True) or {}).get('action')
            result = backend.resolve_mute_recovery(action)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:
            return jsonify(error=str(exc)), 500
        broadcast({'type':'mute-recovery'})
        return jsonify(result)

    @app.get('/api/peaks')
    def get_peaks():
        try:
            return jsonify(backend.peak_snapshot())
        except (ValueError, AttributeError) as exc:
            return jsonify(available=False, error=str(exc)), 400
        except Exception as exc:
            return jsonify(available=False, error=str(exc)), 500

    @app.get('/api/peak-stream')
    def peak_stream():
        """Push one FFADO sample to every viewer instead of HTTP polling.

        Resolve the selected physical backend *before* streaming: Flask's
        request/session context is not available from the generator thread.
        EventSource uses session cookies; it cannot send X-FFADO-Device.
        A device switch closes the old stream in the client, and each frame
        still carries its originating GUID for client-side validation.
        """
        from flask import Response
        selected_backend = backend.manager.backend if hasattr(backend, 'manager') else backend
        sampler, client = peak_streams.subscribe(selected_backend)

        def stream():
            try:
                yield ': connected\n\n'
                while True:
                    try:
                        data = client.get(timeout=2)
                    except queue.Empty:
                        yield ': keepalive\n\n'
                        continue
                    yield 'data: ' + data + '\n\n'
            finally:
                peak_streams.unsubscribe(sampler, client)

        return Response(stream(), mimetype='text/event-stream', headers={
            'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no',
        })

    @app.post('/api/bus-stereo')
    def bus_stereo():
        # Preserve existing hardware semantics: only consecutive 0/1, 2/3,
        # etc. are valid. Names belong to the UI and never change routing.
        try:
            data = request.get_json(silent=True)
            if not isinstance(data, dict) or type(data.get('left')) is not int or type(data.get('linked')) is not bool:
                raise ValueError('Expected integer left bus and boolean linked')
            left, value = data['left'], data['linked']
            if left % 2 or left < 0 or left + 1 >= len(backend.mixes):
                raise ValueError('Select a consecutive odd/even bus pair')
            if not backend.describe().get('matrix', {}).get('available'):
                raise ValueError('No linked bus gain matrix is supported')
        except (ValueError, TypeError, KeyError) as exc:
            return jsonify(error=str(exc)), 400
        with config._save_lock:
            original = list(config.settings.get('stereo_buses', []))
            key = 'bus-pair:' + str(left)
            old_alias = config.names.get(key)
            pairs = list(original)
            if value and left not in pairs:
                pairs.append(left)
            elif not value and left in pairs:
                pairs.remove(left)
            config.settings['stereo_buses'] = pairs
            if not value:
                # Unlink discards only the group alias; original names of
                # both independent buses remain untouched.
                config.names.pop(key, None)
            try:
                config.save()
            except Exception as exc:
                config.settings['stereo_buses'] = original
                if old_alias is not None:
                    config.names[key] = old_alias
                else:
                    config.names.pop(key, None)
                try:
                    config.save()
                except Exception:
                    return jsonify(error='Could not save bus link; rollback may be incomplete'), 500
                return jsonify(error='Could not save bus link: ' + str(exc)), 500
        broadcast({'type': 'bus-stereo', 'left': left, 'linked': value})
        return jsonify(ok=True)

    @app.get("/api/state")
    def get_state():
        mix = request.args.get("mix", 0, type=int)

        stereo_bus = (hasattr(backend, 'matrix') and
                      backend.matrix['mode'] in ('dice_db', 'rme_db') and
                      mix in config.settings.get('stereo_buses', []))
        try:
            # Read both bus legs within one hardware transaction. This keeps
            # the strip level and pan consistent with the matrix editor.
            mixer_state = backend.read_mix(mix, stereo_bus=True) if stereo_bus else backend.read_mix(mix)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:
            return jsonify(error=str(exc)), 500
        for strip_id, entry in mixer_state.items():
            entry["name"] = config.names.get(
                strip_id,
                entry["name"],
            )

        # A stereo pair is drawn as one strip, kept on the left channel.
        for left, right in config.pairs_for(mix):
            if left in mixer_state and right in mixer_state:
                first, second = mixer_state[left], mixer_state[right]

                if left not in config.names:
                    first["name"] = pair_name(first["name"], second["name"])

                first["input"] = pair_name(first["input"], second["input"])
                # One visual fader cannot faithfully report two different
                # matrix levels. Show the louder side, and expose both values
                # with an explicit mismatch indication instead of silently
                # pretending that only the left channel exists.
                if 'fader' in first and 'fader' in second:
                    left_level, right_level = float(first['fader']), float(second['fader'])
                    first['fader'] = max(left_level, right_level)
                    first['pair_faders'] = [left_level, right_level]
                    first['pair_mismatch'] = abs(left_level - right_level) > 0.15
                if stereo_bus and '_matrix_raw' in first and '_matrix_raw' in second:
                    # For an ordered input pair, pan means *input balance*:
                    # Left channel's path to Left bus vs Right channel's path
                    # to Right bus. Do not infer this from summing four routes,
                    # which can hide a stereo-to-mono crossfeed.
                    left_level = first['_matrix_raw'][0]
                    right_level = second['_matrix_raw'][1]
                    # The linked input pair uses peak-normalized diagonal
                    # attenuation, unlike the sum-normalized mono bus pan.
                    # Read the current hardware values on EVERY /api/state:
                    # linking must immediately show the current balance.
                    first['pan'] = input_pair_balance_from_raw(left_level, right_level)
                    first['pan_available'] = first['pan'] is not None
                    notes = []
                    if not first['pan_available']:
                        notes.append('Both diagonal stereo routes are disconnected. '
                                     'Connect a route in the matrix before adjusting balance.')
                    elif left_level <= 16 or right_level <= 16:
                        notes.append('One diagonal route is disconnected. '
                                     'Balance cannot reconnect it; use the matrix editor.')
                    # The knob represents the *ordered diagonals*, not an
                    # entire 2x2 matrix. Mark a derived balance as partial
                    # when custom cross-routes contribute additional sound.
                    first['pan_partial'] = (first['_matrix_raw'][1] > 16 or
                                            second['_matrix_raw'][0] > 16)
                    if first['pan_partial']:
                        notes.append('Cross-routes are also active. The balance '
                                     'shows diagonal levels only; inspect the matrix for actual stereo routing.')
                    if notes:
                        first['pan_note'] = ' '.join(notes)
                    else:
                        first.pop('pan_note', None)
                elif 'pan' in first and 'pan' in second:
                    first['pan'] = (float(first['pan']) + float(second['pan'])) / 2
                if 'mute' in first and 'mute' in second:
                    states = (bool(first['mute']), bool(second['mute']))
                    first['mute'] = all(states)
                    first['mute_partial'] = (any(states) and not all(states)) or bool(
                        first.get('mute_partial') or second.get('mute_partial'))
                if 'solo' in first and 'solo' in second:
                    first['solo'] = bool(first['solo']) and bool(second['solo'])
                first["partner"] = right
                second["partner_of"] = left

        for entry in mixer_state.values():
            entry.pop('_matrix_raw', None)  # private native sum, never a UI control
        return jsonify(mixer_state)

    @app.post("/api/set")
    def set_value():
        msg = request.get_json(force=True)

        strip = msg["strip"]
        control = msg["control"]
        value = msg["value"]

        if control == "name":
            name = str(value).strip()[:16]

            if name:
                config.names[strip] = name
                config.save()

                broadcast(
                    {
                        "type": "name",
                        "strip": strip,
                        "value": name,
                    }
                )

            return jsonify(ok=True)

        mix = int(msg.get('mix', 0))
        pair = config.pair_of(strip, mix) if control in MIRRORED else None
        # A linked DICE/RME output is two distinct matrix rows; an input
        # pair is two distinct matrix columns. Muting must cover their full
        # Cartesian product, not just the visible left-hand strip/bus.
        if control == 'mute' and getattr(backend, '_soft_mute', lambda: False)():
            try:
                if type(value) is not bool:
                    raise ValueError('Mute value must be a boolean')
                stereo_bus = (hasattr(backend, 'matrix') and
                              backend.matrix['mode'] in ('dice_db', 'rme_db') and
                              mix in config.settings.get('stereo_buses', []))
                buses = (mix, mix + 1) if stereo_bus else (mix,)
                channels = [int(channel.split('/')[-1]) for channel in (pair or [strip])]
                backend.write_group_mute(buses, channels, value)
            except (ValueError, TypeError, IndexError, KeyError) as exc:
                return jsonify(error=str(exc)), 400
            except Exception as exc:
                return jsonify(error=str(exc)), 500
            broadcast({'type': 'strip', 'mix': mix,
                       'strip': pair[0] if pair else strip,
                       'control': 'mute', 'value': value})
            return jsonify(ok=True)
        if control == 'pan' and config.pair_of(strip, mix):
            # Stereo pan shifts the L/R image without collapsing both channels
            # to one identical pan position. Center = hard L and hard R.
            left, right = config.pair_of(strip, mix)
            try:
                position = float(value)
                if not -1 <= position <= 1:
                    raise ValueError('Stereo pan must be between -1 and 1')
                mix = int(msg.get('mix', 0))
                left_pan = -1 + 2 * max(0, position)
                right_pan = 1 + 2 * min(0, position)
                matrix_pan = (hasattr(backend, 'matrix') and
                              backend.matrix['mode'] in ('dice_db', 'rme_db'))
                if matrix_pan:
                    # A DICE input pair has no independent hardware pan
                    # control. It needs two output matrix rows. Never fall
                    # through to two non-existent per-channel pan writes.
                    if mix % 2 or mix not in config.settings.get('stereo_buses', []):
                        raise ValueError('Link the stereo output buses first to pan paired DICE/RME inputs')
                    backend.write_input_pair_balance(mix,
                        int(left.split('/')[-1]), int(right.split('/')[-1]), position,
                        activate_missing=True)
                else:
                    # On non-matrix mixers, only call actual source-defined pan
                    # controls. Linking itself never touches hardware controls.
                    for channel, pan_value in ((left, left_pan), (right, right_pan)):
                        backend.write(mix, channel, 'pan', pan_value)
            except (ValueError, TypeError, KeyError, IndexError) as exc:
                return jsonify(error=str(exc)), 400
            except Exception as exc:
                return jsonify(error=str(exc)), 500
            broadcast({'type': 'strip', 'mix': mix, 'strip': left, 'control': 'pan', 'value': position})
            return jsonify(ok=True)
        if control == 'fader' and hasattr(backend, 'matrix') and backend.matrix['mode'] in ('dice_db','rme_db'):
            bus=int(msg.get('mix',0))
            if bus in config.settings.get('stereo_buses', []):
                try:
                    # A paired input strip is one operation: when both inputs
                    # start at -infinity, establish the two DIAGONAL routes,
                    # never both inputs on both outputs. An unpaired mono
                    # input may be explicitly raised into the stereo mix.
                    channels = ([(int(pair[0].split('/')[-1]), 'left'),
                                 (int(pair[1].split('/')[-1]), 'right')]
                                if pair else [(int(strip.split('/')[-1]), 'mono')])
                    backend.write_stereo_levels(bus, channels, float(value))
                except (ValueError,TypeError,IndexError) as exc:
                    return jsonify(error=str(exc)),400
                except Exception as exc:
                    return jsonify(error=str(exc)),500
                broadcast({'type':'strip','mix':bus,'strip':pair[0] if pair else strip,
                           'control':'fader','value':value})
                return jsonify(ok=True)
        if control == 'pan' and hasattr(backend, 'matrix') and backend.matrix['mode'] in ('dice_db','rme_db'):
            mix=int(msg.get('mix',0))
            left = mix - 1 if mix % 2 else mix
            if left in config.settings.get('stereo_buses', []):
                try:
                    backend.write_bus_balance(left, int(strip.split('/')[-1]), float(value))
                except (ValueError,TypeError,IndexError) as exc:
                    return jsonify(error=str(exc)),400
                except Exception as exc:
                    return jsonify(error=str(exc)),500
                broadcast({'type':'strip','mix':left,'strip':strip,'control':'pan','value':value})
                return jsonify(ok=True)

        try:
            if pair:
                write_linked_controls(backend, mix, pair, control, value)
            else:
                backend.write(mix, strip, control, value)
        except (ValueError, KeyError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:
            return jsonify(error=str(exc)), 500

        broadcast(
            {
                "type": "strip",
                "mix": int(msg.get("mix", 0)),
                "strip": pair[0] if pair else strip,
                "control": control,
                "value": value,
            }
        )

        return jsonify(ok=True)

    @app.get("/api/output")
    def get_output():
        out = request.args.get("out", "")

        try:
            output = backend.read_output(out)
            output["name"] = config.names.get("out:" + out, output["name"])

            return jsonify(output)
        except (ValueError, KeyError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:
            return jsonify(error=str(exc)), 500

    @app.post("/api/output")
    def set_output():
        msg = request.get_json(force=True)

        try:
            backend.write_output(
                msg["out"],
                msg["control"],
                msg["value"],
            )
        except (ValueError, KeyError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:
            return jsonify(error=str(exc)), 500

        broadcast(
            {
                "type": "output",
                "out": msg["out"],
                "control": msg["control"],
                "value": msg["value"],
            }
        )

        return jsonify(ok=True)

    @app.get("/api/destination")
    def get_destination():
        try:
            return jsonify(
                backend.read_destination(
                    request.args.get("out", "")
                )
            )
        except (ValueError, KeyError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:
            return jsonify(error=str(exc)), 500

    @app.post("/api/destination")
    def set_destination():
        msg = request.get_json(force=True)

        try:
            backend.write_destination(
                msg["out"],
                int(msg["value"]),
            )
        except (ValueError, KeyError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:
            return jsonify(error=str(exc)), 500

        broadcast(
            {
                "type": "destination",
                "out": msg["out"],
                "value": int(msg["value"]),
            }
        )

        return jsonify(ok=True)

    # FFADO mixer coefficients and EAP crossbar routing are independent.
    # Never treat router endpoints as gain controls.
    @app.get("/api/matrix")
    def matrix_snapshot():
        try:
            return jsonify(backend.matrix_snapshot())
        except (AttributeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:
            return jsonify(error=str(exc)), 500

    @app.post("/api/matrix")
    def matrix_set():
        try:
            body = request.get_json(force=True)
            row, col = int(body["input"]), int(body["output"])
            if "db" in body:
                result = backend.matrix_set(row, col, db=body["db"], use_db=True)
            else:
                result = backend.matrix_set(row, col, body["value"])
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:
            return jsonify(error=str(exc)), 500
        broadcast({"type": "matrix", "input": row, "output": col,
                   "value": result["value"], "db": result.get("db")})
        return jsonify(result)

    @app.get('/api/stereo-firewire')
    def get_stereo_firewire():
        try:
            return jsonify(backend.stereo_firewire_options())
        except (ValueError, AttributeError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:
            return jsonify(error=str(exc)), 500

    @app.post('/api/stereo-firewire')
    def set_stereo_firewire():
        try:
            body = request.get_json(force=True)
            if not isinstance(body, dict) or type(body.get('bus')) is not int:
                raise ValueError('A stereo bus number is required')
            result = backend.stereo_firewire_apply(body.get('left_source'), body['bus'])
        except (TypeError, ValueError, AttributeError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:
            return jsonify(error=str(exc)), 500
        broadcast({'type': 'matrix', 'bus': result['bus'], 'stereo_playback': True})
        return jsonify(result)

    @app.get("/api/router")
    def router_snapshot():
        try:
            return jsonify(backend.router_snapshot())
        except (AttributeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:
            return jsonify(error=str(exc)), 500

    @app.post("/api/router")
    def router_set():
        try:
            body = request.get_json(force=True)
            backend.router_set(str(body["destination"]), str(body["source"]))
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:
            return jsonify(error=str(exc)), 500
        broadcast({"type": "routing", "destination": body["destination"], "source": body["source"]})
        return jsonify(ok=True)

    # Pre-mark3 MOTU: each Mix_dest control routes one entire mix bus.
    # This endpoint does not touch mixer crosspoint gains.
    @app.post('/api/phones-assignment')
    def set_phones_assignment():
        try:
            msg = request.get_json(force=True)
            if not isinstance(msg, dict) or type(msg.get('value')) is not int:
                raise ValueError('Phones destination must be an integer')
            value = backend.write_phones_assignment(msg['value'])
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:
            return jsonify(error=str(exc)), 500
        broadcast({'type': 'destination', 'out': 'phones', 'value': value})
        return jsonify(ok=True, value=value)

    @app.get("/api/bus-routing")
    def bus_routing_snapshot():
        try:
            return jsonify(backend.bus_routing_snapshot())
        except (AttributeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:
            return jsonify(error=str(exc)), 500

    @app.post("/api/bus-routing")
    def bus_routing_set():
        try:
            body = request.get_json(force=True)
            bus_id, value = str(body["bus"]), int(body["value"])
            backend.bus_routing_set(bus_id, value)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:
            return jsonify(error=str(exc)), 500
        broadcast({"type": "destination", "out": bus_id, "value": value})
        return jsonify(ok=True)
