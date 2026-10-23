"""Source-attributed, per-model FFADO capabilities.

'mapped' permits use of a specific webmixer control after D-Bus confirms its
interface. 'optional' permits a runtime feature probe (e.g. peak metering).
'source_only' documents a libffado control which webmixer does not implement;
'unmapped' means unknown/not yet mapped, NOT that hardware lacks the feature.
"""

from xml.etree import ElementTree as ET

FEATURES = frozenset({
    'matrix_gain', 'matrix_pan', 'matrix_mute', 'matrix_solo', 'matrix_invert',
    'matrix_playback', 'matrix_output', 'crossbar_routing', 'peak_metering',
    'software_mute_solo', 'stereo_bus_link', 'bus_destination', 'bus_output_mute',
    'monitor_line_volume', 'monitor_line_mute', 'monitor_global_mute',
    'monitor_global_dim', 'output_level', 'channel_trim', 'channel_invert',
    'device_settings', 'hardware_nickname', 'scalar_volume', 'scalar_selector',
})
STATES = frozenset({'mapped', 'optional', 'source_only', 'unmapped'})
STATUSES = frozenset({'mapped', 'identity_only', 'requires_internal_model'})


def parse_capabilities(device_node):
    tag = device_node.find('capabilities')
    if tag is None or tag.get('schema') != '2' or tag.get('status') not in STATUSES:
        raise ValueError(f"{device_node.get('name', 'Unknown device')}: missing capability schema v2")
    result = {'status':tag.get('status'), 'source':tag.get('source', ''),
              'note':tag.get('note', ''), 'features':{}}
    for entry in tag.findall('feature'):
        name, state = entry.get('name'), entry.get('state')
        if name not in FEATURES or name in result['features'] or state not in STATES:
            raise ValueError(f"{device_node.get('name')}: invalid/duplicate capability {name!r}")
        data = dict(entry.attrib)
        if state in ('mapped','optional','source_only'):
            if not data.get('source') or not data.get('path'):
                raise ValueError(f'{device_node.get("name")}: {name} requires source evidence and path')
            if not data['path'].startswith('/'):
                raise ValueError(f'{device_node.get("name")}: {name} is not an absolute D-Bus suffix')
        if 'count' in data and int(data['count']) < 1:
            raise ValueError('Invalid count')
        result['features'][name] = data
    missing = FEATURES - result['features'].keys()
    if missing:
        raise ValueError(f'{device_node.get("name")}: undeclared features {sorted(missing)}')
    return result


def state(profile, feature):
    return profile.get('capabilities', {}).get('features', {}).get(feature, {}).get('state', 'unmapped')


def enabled(profile, feature):
    return state(profile, feature) == 'mapped'


def probe_allowed(profile, feature):
    return state(profile, feature) in ('mapped', 'optional')


def declared_path(profile, feature):
    if not probe_allowed(profile, feature):
        return None
    return profile['capabilities']['features'][feature].get('path')


def activate_internal_model(profile, internal_model):
    """Resolve FFADO MOTU's Info/Model *before* enabling any mix controls."""
    if profile.get('capabilities', {}).get('status') != 'requires_internal_model':
        return profile
    try:
        key = str(int(internal_model))
    except (TypeError, ValueError):
        raise ValueError('FFADO internal model ID was not available') from None
    model = profile.get('models', {}).get(key)
    if model is None or 'capabilities' not in model:
        raise ValueError(f'Unsupported MOTU internal model {key}; refusing unverified control mapping')
    profile = dict(profile)
    profile['capabilities'] = model['capabilities']
    profile['device_name'] = model.get('name', profile.get('device_name'))
    profile['internal_model_id'] = int(key)
    return profile


def declared_mixer_hint(profile):
    if not enabled(profile, 'matrix_gain'):
        return {}
    hint = profile.get('mixer_matrix') or {}
    if hint.get('path') != declared_path(profile, 'matrix_gain'):
        raise ValueError(f'Matrix hint mismatches model capability: {hint.get("path")}')
    return hint
