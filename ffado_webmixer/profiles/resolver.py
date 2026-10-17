"""Map live FFADO endpoints using hardware family conventions, not matrix size.

DICE EAP: mixer *rows are inputs*, *columns are outputs* (see
libffado/src/dice/dice_eap.cpp, EAP::Mixer). Other families normally use
rows=output buses, columns=inputs. A CrossbarRouter is not a gain matrix.
"""
import re

ROLE_WORDS = (("fader", ("fader", "gain", "volume", "level")),
              ("pan", ("pan",)), ("mute", ("mute",)), ("solo", ("solo",)))


def _role(name):
    low = name.lower()
    for role, words in ROLE_WORDS:
        if any(word in low for word in words):
            return role
    return low or "matrix"


def _dice_input_label(label, number):
    """FFADO includes the router source on a second line of each mixer input."""
    parts = str(label).split("\n", 1)
    attached = parts[1].strip().strip("()") if len(parts) > 1 else ""
    if attached and not attached.startswith("Mute:"):
        return attached
    return parts[0] or f"Mix In {number}"


def resolve_mixer(device, profile):
    """Return real matrix roles and the orientation understood by Mixer.

    Matrix selection is explicit for devices supported by libffado's own
    mixer UIs. Unknown matrix families are displayed but never misclassified
    as writable gain just because they have many cells.
    """
    matrices = [m for m in device.get("matrices", []) if m.get("rows", 0) and m.get("cols", 0)]
    if not matrices:
        return None
    family = profile.get("family", "")
    def at(suffix):
        return next((m for m in matrices if m["path"].endswith(suffix)), None)
    primary = None
    transpose = False
    mode = "linear"
    hint = profile.get("mixer_matrix", {})
    if hint:
        primary = at(hint.get("path", "__unused__"))
        if primary:
            transpose = hint.get("row_role") == "inputs"
            mode = hint.get("coefficient", "linear")
    if primary is None and (family in ("saffire_dice", "generic_dice_eap", "profire2626") or any(
            m["path"].endswith("/EAP/MatrixMixer") for m in matrices)):
        primary = at("/EAP/MatrixMixer")
        if primary:
            transpose = True
            mode = "dice_db"
    if primary is None:
        primary = at("/Mixer/fader") or at("/Mixer/InputFaders") or at("/Mixer/PlaybackFaders")
    if primary is None:
        primary = next((m for m in matrices if re.search(r"(?:faders?|levels?|gains?)$", m["name"], re.I)), None)
    if primary is None:
        # Fallback to a display-only matrix; never pretend it is a fader.
        primary = max(matrices, key=lambda m: m["rows"] * m["cols"])
        mode = "unmapped"
    chosen = [m for m in matrices if m["rows"] == primary["rows"] and m["cols"] == primary["cols"]]
    roles = {}
    if mode != "unmapped":
        roles["fader"] = primary["path"]
        for m in chosen:
            if m is primary:
                continue
            role = _role(m["name"])
            if role in ("mute", "solo", "pan") and role not in roles:
                roles[role] = m["path"]
    row_names = primary.get("row_names", [])
    col_names = primary.get("col_names", [])
    if transpose:
        # libffado's MatrixMixer(..., 'Columns_are_outputs') does the same.
        buses = [str(name).split("\n")[0] or f"Mix Out {i+1}" for i, name in enumerate(col_names)]
        channels = [_dice_input_label(name, i + 1) for i, name in enumerate(row_names)]
    else:
        buses = [name or f"Mix {i+1}" for i, name in enumerate(row_names)]
        channels = [name or f"Channel {i+1}" for i, name in enumerate(col_names)]
    return {"rows": buses, "columns": channels, "capabilities": sorted(roles),
            "matrices": roles, "path": primary["path"], "transposed": transpose,
            "mode": mode, "matrix_rows": primary["rows"], "matrix_cols": primary["cols"]}

# Interpret discovered endpoint labels and model-specific visibility in the profile layer.
VALUE_KINDS = ("Discrete", "Continuous", "Boolean")
CHANNEL_WORDS = {"gain": ("trim", "gain", "preamp"), "invert": ("invert", "polarity", "phase")}
DEFAULT_CONTROLS = {role: {"type": "toggle", "min": 0, "max": 1} for role in ("mute", "solo", "invert")}


def bus_name(row_name):
    import re
    return re.sub(r"^\s*mix\b", "Bus", row_name, flags=re.I)


def match_outputs(device, mixes, profile=None):
    """Resolve live output endpoints using discovered labels."""
    controls = [c for c in device["controls"] if c["kind"] in VALUE_KINDS]
    def find(pred):
        return next((c for c in controls if pred(c["label"].lower())), None)
    outputs = {}
    family = (profile or {}).get("family", "")
    # Focusrite's monitoring level controls are scalar Discrete elements.
    # Use only endpoints discovered on the connected device, never invented paths.
    if family == "saffire_dice":
        by_suffix = {c["path"].split("/EAP/Monitoring/")[-1]: c for c in controls
                     if "/EAP/Monitoring/" in c["path"]}
        for i in range(1, 11):
            fader = by_suffix.get(f"LineOut/Volume{i}")
            if fader and fader["kind"] == "Discrete":
                outputs[f"line/{i}"] = {
                    "id": f"line/{i}", "name": f"Line Out {i}", "mix": None,
                    "fader": fader, "mute": by_suffix.get(f"LineOut/Mute{i}"),
                    "dest": None, "spec": {"min": -40, "max": 0, "writable": True},
                }
    for out_id, name, word in (("main", "Main", "main"), ("phones", "Phones", "phones")):
        fader = find(lambda label, w=word: w in label and "fader" in label)
        if fader:
            outputs[out_id] = {"id": out_id, "name": name, "mix": None, "fader": fader, "mute": None, "dest": None}
    for i, row in enumerate(mixes):
        prefix = row.lower() + " "
        fader = find(lambda label, p=prefix: label.startswith(p) and "fader" in label[len(p):])
        mute = find(lambda label, p=prefix: label.startswith(p) and "mute" in label[len(p):])
        dest = find(lambda label, p=prefix: label.startswith(p) and "dest" in label[len(p):])
        if family == "motu":
            # libffado/src/motu/motu_mixer.cpp publishes these named Discrete
            # elements. Their getValue/setValue select the *destination* of a
            # whole mix bus; they are not matrix gain coefficients. Labels vary
            # between FFADO versions, but the source-defined paths do not.
            suffix = f"/Mixer/Mix{i + 1}/Mix_dest"
            dest = next((c for c in controls
                         if c["path"].endswith(suffix) and c["kind"] == "Discrete"), None)
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
        if role == "fader" and path.endswith("/EAP/MatrixMixer"):
            # The DICE register is a linear coefficient, 0..65535;
            # FFADO's UI presents -60..+6 dB around unity=16384.
            spec = {"type": "dice_db", "min": 0, "max": 65535}
        elif role == "fader" and (path.endswith("/Mixer/InputFaders") or
                                  path.endswith("/Mixer/PlaybackFaders") or
                                  path.endswith("/Mixer/OutputFaders")):
            # RME's FFADO Qt mixer uses sliderMaxValue=0x8000, unity=0x4000.
            spec = {"type": "rme_db", "min": 0, "max": 32768}
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
            "outputs": match_outputs(device, mixes, profile),
            "output_spec": dict(output_spec or {"min": 0, "max": 1}, writable=bool(output_spec))}

