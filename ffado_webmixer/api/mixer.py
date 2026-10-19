from flask import jsonify, request
from ..services.stereo import MIRRORED, pair_name
from ..mixer import input_pair_balance_from_raw

def register(app, backend, description, config, broadcast):
    @app.get("/api/describe")
    def describe():
        # Output names (Main, Phones, buses) can be renamed in the UI; saved names win.
        result = dict(backend.describe())
        result['stereo_buses'] = config.settings.get('stereo_buses', [])
        result["outputs"] = [
            dict(output, base_name=output["name"], name=config.names.get("out:" + output["id"], output["name"]))
            for output in result.get("outputs", [])
        ]

        return jsonify(result)

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

    @app.post('/api/bus-stereo')
    def bus_stereo():
        try:
            data=request.get_json(force=True)
            left=int(data.get('left',-1)); value=bool(data.get('linked',False))
            if left % 2 or left < 0 or left+1 >= len(backend.mixes):
                raise ValueError('Select a consecutive odd/even bus pair')
            if not backend.describe().get('matrix',{}).get('available'):
                raise ValueError('No linked bus gain matrix is supported')
            pairs=config.settings.setdefault('stereo_buses',[])
            if value and left not in pairs: pairs.append(left)
            elif not value and left in pairs: pairs.remove(left)
            config.save()
        except (ValueError,TypeError,KeyError) as exc:
            return jsonify(error=str(exc)),400
        broadcast({'type':'bus-stereo','left':left,'linked':value})
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
                if (hasattr(backend, 'matrix') and
                        backend.matrix['mode'] in ('dice_db', 'rme_db') and
                        (mix - mix % 2) in config.settings.get('stereo_buses', [])):
                    if mix % 2:
                        raise ValueError('Select the left stereo output bus to adjust an input pair')
                    backend.write_input_pair_balance(mix,
                        int(left.split('/')[-1]), int(right.split('/')[-1]), position)
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
                    for channel in pair or [strip]:
                        backend.write_stereo_level(bus,int(channel.split('/')[-1]),float(value))
                except (ValueError,TypeError) as exc:
                    return jsonify(error=str(exc)),400
                except Exception as exc:
                    return jsonify(error=str(exc)),500
                broadcast({'type':'strip','mix':bus,'strip':strip,'control':'fader','value':value})
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
            written = 0
            refused = None

            for target in pair or [strip]:
                try:
                    backend.write(
                        int(msg.get("mix", 0)),
                        target,
                        control,
                        value,
                    )
                    written += 1
                except ValueError as exc:
                    # One channel of a pair may lack a control the other has (e.g. no input gain).
                    refused = exc

            if not written and refused:
                raise refused
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
