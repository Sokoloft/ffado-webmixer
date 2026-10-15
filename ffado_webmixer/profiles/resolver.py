"""Interpret discovered FFADO endpoints using resolved profile metadata."""
from collections import Counter

# Only the live endpoints reported by FFADO may be used. The family XML
# supplies control semantics/ranges; generic classification is a fallback.
ROLE_WORDS = (("fader", ("fader", "gain", "volume", "level")),
              ("pan", ("pan",)), ("mute", ("mute",)), ("solo", ("solo",)))


def _role(name):
    low = name.lower()
    for role, words in ROLE_WORDS:
        if any(word in low for word in words):
            return role
    return low or "matrix"


def resolve_mixer(device, profile):
    """Interpret live matrix inventory with the selected XML family profile.

    Never create endpoints from reference.xml or guessed control paths.
    """
    matrices = device.get("matrices", [])
    if not matrices:
        return None
    shapes = Counter((m["rows"], m["cols"]) for m in matrices)
    rows, cols = max(shapes, key=lambda shape: (shapes[shape], shape[0] * shape[1]))
    grid = [m for m in matrices if (m["rows"], m["cols"]) == (rows, cols)]
    roles = {}
    for matrix in grid:
        role = _role(matrix["name"])
        roles[role if role not in roles else matrix["name"]] = matrix["path"]
    return {
        "rows": [name or f"Mix {i + 1}" for i, name in enumerate(grid[0]["row_names"])],
        "columns": [name or f"Channel {i + 1}" for i, name in enumerate(grid[0]["col_names"])],
        "capabilities": sorted(roles),
        "matrices": roles,
    }


# Interpret discovered endpoint labels and model-specific visibility in the profile layer.
VALUE_KINDS = ("Discrete", "Continuous", "Boolean")
CHANNEL_WORDS = {"gain": ("trim", "gain", "preamp"), "invert": ("invert", "polarity", "phase")}
DEFAULT_CONTROLS = {role: {"type": "toggle", "min": 0, "max": 1} for role in ("mute", "solo", "invert")}


def bus_name(row_name):
    import re
    return re.sub(r"^\s*mix\b", "Bus", row_name, flags=re.I)


def match_outputs(device, mixes):
    """Resolve live output endpoints using discovered labels."""
    controls = [c for c in device["controls"] if c["kind"] in VALUE_KINDS]
    def find(pred):
        return next((c for c in controls if pred(c["label"].lower())), None)
    outputs = {}
    for out_id, name, word in (("main", "Main", "main"), ("phones", "Phones", "phones")):
        fader = find(lambda label, w=word: w in label and "fader" in label)
        if fader:
            outputs[out_id] = {"id": out_id, "name": name, "mix": None, "fader": fader, "mute": None, "dest": None}
    for i, row in enumerate(mixes):
        prefix = row.lower() + " "
        fader = find(lambda label, p=prefix: label.startswith(p) and "fader" in label[len(p):])
        mute = find(lambda label, p=prefix: label.startswith(p) and "mute" in label[len(p):])
        dest = find(lambda label, p=prefix: label.startswith(p) and "dest" in label[len(p):])
        outputs[f"bus/{i}"] = {"id": f"bus/{i}", "name": bus_name(row), "mix": i, "fader": fader, "mute": mute, "dest": dest}
    return outputs


def match_channel_controls(device, columns):
    """Associate independent scalar endpoints with their physical input."""
    found = {}
    for control in device["controls"]:
        if control["kind"] not in VALUE_KINDS:
            continue
        label = control["label"].lower()
        for col, name in enumerate(columns):
            prefix = name.lower() + " "
            if not label.startswith(prefix):
                continue
            rest = label[len(prefix):]
            for role, words in CHANNEL_WORDS.items():
                if any(word in rest for word in words):
                    found.setdefault(col, {}).setdefault(role, control)
    return found


def visible_columns(profile, model, columns, sample_rate=None):
    from fnmatch import fnmatch
    model_data = profile.get("models", {}).get(str(model), {})
    hidden = list(model_data.get("hide_cols", []))
    for rule in profile.get("rate_rules", []):
        if sample_rate is not None and sample_rate > rule["above"]:
            hidden.extend(rule["hide_cols"])
    return [i for i, name in enumerate(columns) if not any(fnmatch(name, pattern) for pattern in hidden)]


def destination_options(profile, model, current=None):
    from fnmatch import fnmatch
    model_data = profile.get("models", {}).get(str(model), {})
    names = {d["value"]: d["name"] for d in profile.get("destinations", [])}
    names.update({int(k): v for k, v in model_data.get("dest_names", {}).items()})
    outputs = {d["value"]: d["output"] for d in profile.get("destinations", []) if d.get("output")}
    outputs.update({int(k): v for k, v in model_data.get("dest_outputs", {}).items()})
    options = []
    for value, name in sorted(names.items()):
        if any(fnmatch(name, pattern) for pattern in model_data.get("hide_dests", [])):
            continue
        options.append({"value": value, "name": name, **({"output": outputs[value]} if value in outputs else {})})
    if current is not None and current not in [option["value"] for option in options]:
        options.append({"value": current, "name": f"Unavailable ({names.get(current, current)})"})
    return options


def resolve_controls(device, profile, matrices, columns, mixes):
    """Return live endpoint mappings and writable metadata, never synthetic paths."""
    specs = profile.get("controls", {})
    roles = {}
    for role, path in matrices.items():
        spec = specs.get(role) or DEFAULT_CONTROLS.get(role)
        binary = role in ("mute", "solo", "invert")
        roles[role] = (path, dict(spec or {"type": "toggle" if binary else "unknown"}, writable=bool(spec) or binary))
    channels = match_channel_controls(device, columns)
    channel_specs = {}
    for role in CHANNEL_WORDS:
        spec = specs.get(role) or DEFAULT_CONTROLS.get(role)
        available = role == "invert" and any(role in channel for channel in channels.values())
        channel_specs[role] = dict(spec or {"type": "unknown"}, writable=bool(spec) or available)
    output_spec = specs.get("output_fader")
    return {"roles": roles, "channels": channels, "channel_specs": channel_specs,
            "outputs": match_outputs(device, mixes),
            "output_spec": dict(output_spec or {"min": 0, "max": 1}, writable=bool(output_spec))}

