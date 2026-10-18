"""Map live FFADO endpoints using hardware family conventions, not matrix size.

DICE EAP: mixer *rows are inputs*, *columns are outputs* (see
libffado/src/dice/dice_eap.cpp, EAP::Mixer). Other families normally use
rows=output buses, columns=inputs. A CrossbarRouter is not a gain matrix.
"""
import re
from .capabilities import enabled, declared_path, declared_mixer_hint

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
    hint = declared_mixer_hint(profile)
    if hint:
        primary = at(hint.get("path", "__unused__"))
        if primary:
            transpose = hint.get("row_role") == "inputs"
            mode = hint.get("coefficient", "linear")
    # No family-name fallback: a model must declare its precise matrix path,
    # orientation, and coefficient convention in its source-derived XML.
    # Having the same-looking D-Bus node is not enough to enable writes.
    if primary is None:
        # Don't invent topology from a similarly sized/named D-Bus matrix.
        # Hardware endpoints remain inspectable with FFADO diagnostics.
        return None
    chosen = [m for m in matrices if m["rows"] == primary["rows"] and m["cols"] == primary["cols"]]
    roles = {'fader':primary['path']} if mode != 'unmapped' else {}
    # MOTU's independent named fader/pan/mute/solo matrices are explicitly
    # documented in motu.py and src/motu/motu_mixer.cpp.
    if family == 'motu':
        for role in ('pan', 'mute', 'solo'):
            if not enabled(profile, 'matrix_'+role):
                continue
            candidate = at(declared_path(profile, 'matrix_'+role))
            if candidate and candidate in chosen:
                roles[role] = candidate['path']
    if family == 'rme' and mode != 'unmapped':
        for role in ('mute', 'invert'):
            if not enabled(profile, 'matrix_'+role):
                continue
            candidate=at(declared_path(profile, 'matrix_'+role))
            if candidate and candidate in chosen:
                roles[role]=candidate['path']
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
    """Map only source-declared scalar controls; never infer roles from labels."""
    family = (profile or {}).get('family', '')
    controls = {c['path'].rsplit('/DeviceManager/', 1)[-1].split('/', 1)[-1]: c
                for c in device.get('controls', [])}
    def get(suffix, kind=None):
        c = controls.get(suffix.lstrip('/'))
        return c if c and (kind is None or c['kind'] == kind) else None
    outputs = {}
    if family == 'saffire_dice' and enabled(profile, 'monitor_line_volume'):
        count = int(profile['capabilities']['features']['monitor_line_volume'].get('count', '0'))
        for i in range(1, count+1):
            fader = get(declared_path(profile, 'monitor_line_volume').replace('{n}',str(i)), 'Discrete')
            if fader:
                outputs[f'line/{i}'] = {
                    'id':f'line/{i}', 'name':f'Line Out {i}', 'mix':None,
                    'fader':fader, 'mute':get(declared_path(profile, 'monitor_line_mute').replace('{n}',str(i)), 'Boolean') if enabled(profile, 'monitor_line_mute') else None,
                    'dest':None, 'spec':{'min':-40,'max':0,'writable':True}}
    if family == 'motu' and enabled(profile, 'output_level'):
        extra = profile['capabilities']['features']['output_level'].get('extra_paths', '').split(',')
        for out_id,name,path in (('main','Main','Mainout_fader'),('phones','Phones','Phones_fader')):
            if '/Mixer/'+path not in extra:
                continue
            fader=get(f'Mixer/{path}','Discrete')
            if fader:
                outputs[out_id]={'id':out_id,'name':name,'mix':None,'fader':fader,
                                 'mute':None,'dest':None}
    for i,row in enumerate(mixes):
        if family == 'motu' and enabled(profile, 'output_level'):
            base=f'Mixer/Mix{i+1}/Mix_'
            fader=get(declared_path(profile, 'output_level').replace('{n}',str(i+1)), 'Discrete')
            mute=get(declared_path(profile, 'bus_output_mute').replace('{n}',str(i+1))) if enabled(profile, 'bus_output_mute') else None
            dest=get(declared_path(profile, 'bus_destination').replace('{n}',str(i+1)), 'Discrete') if enabled(profile, 'bus_destination') else None
        else:
            fader=mute=dest=None
        outputs[f'bus/{i}']={'id':f'bus/{i}', 'name':bus_name(row), 'mix':i,
                             'fader':fader,'mute':mute,'dest':dest}
    return outputs


def match_channel_controls(device, columns, profile=None):
    """Only known MOTU per-channel Discrete controls from motu.py."""
    if (profile or {}).get('family') != 'motu' or not (enabled(profile, 'channel_trim') or enabled(profile, 'channel_invert')):
        return {}
    controls={c['path'].split('/Mixer/Control/')[-1]:c for c in device.get('controls', [])
              if '/Mixer/Control/' in c['path']}
    import re
    result={}
    for i,name in enumerate(columns):
        match=re.fullmatch(r'(?:Analog|SPDIF)\s*(\d+)',name,re.I)
        if not match: continue
        prefix=('Ana' if name.lower().startswith('analog') else 'Spdif')+match.group(1)
        for role,suffix in (('gain','_trimgain'),('invert','_invert')):
            if not enabled(profile, 'channel_trim' if role=='gain' else 'channel_invert'):
                continue
            feature_name = 'channel_trim' if role == 'gain' else 'channel_invert'
            feature = profile['capabilities']['features'][feature_name]
            templates = [feature.get('path','')] + [v for v in feature.get('extra_paths','').split(',') if v]
            allowed = {template.replace('{n}', match.group(1)) for template in templates}
            c=controls.get(prefix+suffix)
            if c and any(c['path'].endswith(path) for path in allowed):
                result.setdefault(i,{})[role]=c
    return result


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
    channels = match_channel_controls(device, columns, profile)
    channel_specs = {}
    for role in CHANNEL_WORDS:
        spec = specs.get(role) or DEFAULT_CONTROLS.get(role)
        available = role == "invert" and any(role in channel for channel in channels.values())
        channel_specs[role] = dict(spec or {"type": "unknown"}, writable=bool(spec) or available)
    output_spec = specs.get("output_fader")
    return {"roles": roles, "channels": channels, "channel_specs": channel_specs,
            "outputs": match_outputs(device, mixes, profile),
            "output_spec": dict(output_spec or {"min": 0, "max": 1}, writable=bool(output_spec))}

