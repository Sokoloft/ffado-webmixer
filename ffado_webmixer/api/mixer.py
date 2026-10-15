from flask import jsonify, request
from ..services.stereo import MIRRORED, pair_name

def register(app, backend, description, config, broadcast):
    @app.get("/api/describe")
    def describe():
        # Output names (Main, Phones, buses) can be renamed in the UI; saved names win.
        result = dict(description)
        result["outputs"] = [
            dict(output, base_name=output["name"], name=config.names.get("out:" + output["id"], output["name"]))
            for output in description.get("outputs", [])
        ]

        return jsonify(result)

    @app.get("/api/state")
    def get_state():
        mix = request.args.get("mix", 0, type=int)

        try:
            mixer_state = backend.read_mix(mix)
        except Exception as exc:
            return jsonify(error=str(exc)), 500

        for strip_id, entry in mixer_state.items():
            entry["name"] = config.names.get(
                strip_id,
                entry["name"],
            )

        # A stereo pair is drawn as one strip, kept on the left channel.
        for left, right in config.stereo:
            if left in mixer_state and right in mixer_state:
                first, second = mixer_state[left], mixer_state[right]

                if left not in config.names:
                    first["name"] = pair_name(first["name"], second["name"])

                first["input"] = pair_name(first["input"], second["input"])
                first["partner"] = right
                second["partner_of"] = left

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

        pair = config.pair_of(strip) if control in MIRRORED else None

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
