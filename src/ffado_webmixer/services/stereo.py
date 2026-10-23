"""Validated, bus-scoped stereo pairing; never writes an audio route."""
import re
from flask import jsonify

MIRRORED = ("fader", "mute", "solo", "gain", "invert")


def pair_name(a, b):
    """'Analog 3' + 'Analog 4' -> 'Analog 3+4'; 'Kick' + 'Snare' -> 'Kick + Snare'."""
    first = re.match(r"^(.*?)(\d+)$", a)
    second = re.match(r"^(.*?)(\d+)$", b)
    if first and second and first.group(1) == second.group(1):
        return f"{first.group(1)}{first.group(2)}+{second.group(2)}"
    return f"{a} + {b}"


def _valid_mix(mix, description):
    """Do not let a negative Python index modify another bus's pair list."""
    if isinstance(mix, bool) or not isinstance(mix, int) or mix < 0:
        return False
    buses = description.get('mixes', []) if isinstance(description, dict) else []
    return isinstance(buses, list) and any(
        (entry.get('id', idx) if isinstance(entry, dict) else idx) == mix
        for idx, entry in enumerate(buses)
    )


def _notices(config, mix, *ids):
    """Describe the specific conflicting channel without changing pair state."""
    for strip in ids:
        pair = config.pair_of(strip, mix)
        if pair:
            return (f"Channel {strip} is already linked with "
                    f"{pair[1] if pair[0] == strip else pair[0]} on this bus. "
                    "Unlink that pair first.")
    return None


def change_stereo(msg, mix, backend, description, config, broadcast):
    if not isinstance(msg, dict):
        return jsonify(error='Expected a stereo operation object'), 400
    if not _valid_mix(mix, description):
        return jsonify(error='Invalid output bus'), 400

    action = msg.get('action')
    if action == 'link':
        # FIRST clicked channel is Left; SECOND clicked channel is Right,
        # regardless of channel ID, adjacency, or fader position.
        left, right = msg.get('dragged'), msg.get('target')
        if (not isinstance(left, str) or not isinstance(right, str)
                or not left.strip() or not right.strip() or left == right):
            return jsonify(error='Choose two different input channels'), 400

        try:
            visible = backend.read_mix(mix)
        except (ValueError, IndexError, KeyError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:
            return jsonify(error=str(exc)), 500
        if not isinstance(visible, dict) or left not in visible or right not in visible:
            return jsonify(error='One or both input channels are unavailable on this bus'), 400

        # Both validation and commit must happen under ONE lock. Two browsers
        # may submit overlapping pair requests at the same instant.
        with config._pair_lock:
            conflict = _notices(config, mix, left, right)
            if conflict:
                return jsonify(error=conflict), 400
            # An I/O error during persistence must not leave an unpersisted
            # pair in memory. (The hardware matrix is never touched.)
            key = str(mix)
            previous = config.stereo_by_mix.get(key)
            try:
                config.link(left, right, mix)
                config.place_pair_in_layout(mix, left, right, left)
                config.save()
            except (ValueError, OSError) as exc:
                if previous is None:
                    config.stereo_by_mix.pop(key, None)
                else:
                    config.stereo_by_mix[key] = previous
                return jsonify(error=str(exc)), 400 if isinstance(exc, ValueError) else 500

        if hasattr(backend, 'forget_input_pair_balance'):
            backend.forget_input_pair_balance(left, right, mix)
        broadcast({'type': 'stereo', 'mix': mix})
        return jsonify(ok=True, left=left, right=right)

    if action == 'unlink':
        strip = msg.get('id')
        if not isinstance(strip, str) or not strip.strip():
            return jsonify(error='Choose a linked input channel to unlink'), 400

        with config._pair_lock:
            pair = config.pair_of(strip, mix)
            if pair is None:
                return jsonify(error='This channel is not linked on this bus'), 400
            key = str(mix)
            previous_pairs = config.stereo_by_mix.get(key)
            previous_layout = config.layouts.get(key)
            try:
                config.unlink(strip, mix)
                config.spread_unlinked(pair[0], pair[1], mix)
                config.save()
            except (ValueError, OSError) as exc:
                if previous_pairs is None:
                    config.stereo_by_mix.pop(key, None)
                else:
                    config.stereo_by_mix[key] = previous_pairs
                if previous_layout is None:
                    config.layouts.pop(key, None)
                else:
                    config.layouts[key] = previous_layout
                return jsonify(error=str(exc)), 400 if isinstance(exc, ValueError) else 500

        if hasattr(backend, 'forget_input_pair_balance'):
            backend.forget_input_pair_balance(*pair, mix)
        broadcast({'type': 'stereo', 'mix': mix})
        return jsonify(ok=True, left=pair[0], right=pair[1])

    return jsonify(error='Unknown stereo action'), 400
