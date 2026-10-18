"""Stereo pair naming, mirrored controls, and linking operations."""
import re
from flask import jsonify

MIRRORED = ("fader", "mute", "solo", "gain", "invert")

def pair_name(a, b):
    """'Analog 3' + 'Analog 4' -> 'Analog 3+4';  'Kick' + 'Snare' -> 'Kick + Snare'."""
    first = re.match(r"^(.*?)(\d+)$", a)
    second = re.match(r"^(.*?)(\d+)$", b)

    if first and second and first.group(1) == second.group(1):
        return f"{first.group(1)}{first.group(2)}+{second.group(2)}"

    return f"{a} + {b}"

def change_stereo(msg, mix, backend, description, config, broadcast):
    mixes = [m["id"] for m in description.get("mixes", [])] or [0]

    def try_write(bus, strip, control, value):
        try:
            backend.write(bus, strip, control, value)
        except ValueError:
            pass          # this device has no such control (e.g. no pan or solo)

    if msg.get("action") == "link":
        dragged, target = msg.get("dragged"), msg.get("target")

        if not isinstance(dragged, str) or not isinstance(target, str) or dragged == target:
            return jsonify(error="pick two different channels"), 400

        if config.pair_of(dragged) or config.pair_of(target):
            return jsonify(error="a channel can only be in one stereo pair"), 400

        try:
            visible = backend.read_mix(mix)
        except Exception as exc:
            return jsonify(error=str(exc)), 500

        if dragged not in visible or target not in visible:
            return jsonify(error="unknown channel"), 400

        left, right = sorted((dragged, target))      # zero-based even = channel 1/3/5 (left)
        try:
            left_index=int(left.split('/')[1]); right_index=int(right.split('/')[1])
        except (ValueError, IndexError):
            return jsonify(error='Invalid input pair'), 400
        if left_index % 2 != 0 or right_index != left_index+1:
            return jsonify(error='Only adjacent odd(L)/even(R) hardware inputs can be linked'), 400

        # The right channel takes the left one's settings, on every bus, and the pair is panned hard left / right.
        for bus in mixes:
            try:
                channels = backend.read_mix(bus)
            except Exception:
                continue

            source = channels.get(left)

            if source is None or right not in channels:
                continue

            for control in MIRRORED:
                if control in source:
                    # The fader goes to both so they match exactly, even if 0-100 rounds a device step.
                    for strip in ((right, left) if control == "fader" else (right,)):
                        try_write(bus, strip, control, source[control])

            try_write(bus, left, "pan", -1)
            try_write(bus, right, "pan", 1)

        # Gain and polarity belong to the channel (the same on every bus): the right takes the left's.
        for control in ("gain", "invert"):
            if control in visible[left]:
                try_write(mix, right, control, visible[left][control])

        config.link(left, right)
        config.place_pair_in_layout(mix, left, right, target)
        config.save()
        broadcast({"type": "stereo"})

        return jsonify(ok=True)

    if msg.get("action") == "unlink":
        pair = config.pair_of(str(msg.get("id", "")))

        if pair is None:
            return jsonify(error="that channel isn't in a stereo pair"), 400

        for bus in mixes:                           # both channels go back to the center
            for strip in pair:
                try_write(bus, strip, "pan", 0)

        config.unlink(pair[0])
        config.spread_unlinked(pair[0], pair[1])
        config.save()
        broadcast({"type": "stereo"})

        return jsonify(ok=True)

    return jsonify(error="unknown action"), 400
