"""Read validated runtime XML profiles; reference.xml is archival, not executable.

A family is selected only by explicit FFADO vendor/model identifiers in common.xml.
The model-specific ID comes from FFADO's Info/Model control, NOT ConfigRom model_id.
"""
from pathlib import Path
from ..device_registry import resolve_device
import xml.etree.ElementTree as ET

ROOT = Path(__file__).parent


def _number(value):
    if value is None:
        raise ValueError('Missing XML numeric value')
    return int(value, 0) if value.lower().startswith('0x') else int(value)


def _common(path):
    root = ET.parse(path).getroot()
    match = root.find('match')
    result = {'match': {k: _number(v) for k, v in match.attrib.items()} if match is not None else {},
              'controls': {}, 'models': {}, 'rate_rules': [], 'destinations': [],
              'discovery_paths': [], 'model_constants': {}, 'source_bindings': []}
    result['family'] = root.get('family')
    matrix_hint = root.find('mixer_matrix')
    result['mixer_matrix'] = dict(matrix_hint.attrib) if matrix_hint is not None else {}
    result['discovery_paths'] = [x.get('path') for x in root.findall('./discovery/element')]
    for constant in root.findall('./model_constants/constant'):
        name, value = constant.get('name'), constant.get('value')
        if not name or not value:
            continue
        try:
            result['model_constants'][name] = _number(value.strip())
        except ValueError:
            continue  # Some source constants are expressions, not numeric literals.
    result['source_bindings'] = [dict(x.attrib, tag=x.tag) for x in root.findall('./source_bindings/*')]
    for info in root.findall('info'):
        result[info.get('name')] = info.get('path')
    for c in root.findall('./controls/control'):
        result['controls'][c.get('name')] = {k: (_number(v) if k in ('min', 'max') else v)
                                           for k, v in c.attrib.items() if k != 'name'}
    for d in root.findall('./destinations/destination'):
        result['destinations'].append({k: (_number(v) if k == 'value' else v) for k,v in d.attrib.items()})
    for rule in root.findall('./rate_rules/rule'):
        result['rate_rules'].append({'above': _number(rule.get('above')),
                                     'hide_cols': [x.get('pattern') for x in rule.findall('hide_col')]})
    for file in path.parent.glob('*.xml'):
        if file.name in ('common.xml', 'reference.xml'):continue
        try:
            node = ET.parse(file).getroot()
        except ET.ParseError:
            continue
        if node.tag != 'device' or node.get('extends') != 'common.xml':continue
        model = {'name':node.get('name'),
                 'hide_cols':[x.get('pattern') for x in node.findall('hide_col')],
                 'hide_dests':[x.get('pattern') for x in node.findall('hide_dest')],
                 'dest_names':{x.get('index'):x.get('value') for x in node.findall('dest_name')},
                 'dest_outputs':{x.get('index'):x.get('value') for x in node.findall('dest_output')}}
        # FFADO configuration identity profiles have no Info/Model ID.
        # Only register model overrides when the internal model ID exists.
        model_id = node.get('model_id')
        if model_id is not None:
            result['models'][str(_number(model_id))] = model
    return result


def _observed_paths(device):
    """Only paths actually reported by FFADO count as available."""
    paths = [c['path'] for c in device.get('controls', [])]
    paths += [m['path'] for m in device.get('matrices', [])]
    prefix = device.get('device', '').rstrip('/')
    return {p[len(prefix):] if prefix and p.startswith(prefix + '/') else p
            for p in paths}


def load_profile(device):
    """Select a family using FFADO identity, or unique observed control signatures.

    Never guess a family from generic names such as /Mixer/fader. An unknown
    device remains usable through the existing generic D-Bus enumeration.
    """
    identity = resolve_device(device)
    mixer_name = identity.get('mixer_name')
    if mixer_name:
        # FFADO's mixer module names correspond to profile directory names.
        family = mixer_name.lower()
        family_path = ROOT / family / 'common.xml'
        if family_path.is_file():
            profile = _common(family_path)
            profile['match_method'] = 'ffado_configuration'
            profile['ffado_identity'] = identity
            # Device-specific files inherit common.xml. Only exact identities
            # are applied; never use the internal Info/Model value as a ConfigRom ID.
            vendor = int(device.get('vendor_id', 0))
            model = int(identity['configuration_model_id'])
            for file in sorted(family_path.parent.glob('*.xml')):
                if file.name in ('common.xml', 'reference.xml'):
                    continue
                try:
                    node = ET.parse(file).getroot()
                except ET.ParseError:
                    continue
                match = node.find('match')
                if (node.tag != 'device' or match is None or
                    node.get('extends') != 'common.xml'):
                    continue
                try:
                    matches = (int(match.get('vendor_id', '-1'), 0) == vendor and
                               int(match.get('configuration_model_id', '-1'), 0) == model)
                except ValueError:
                    matches = False
                if matches:
                    profile['device_profile'] = file.name
                    profile['device_name'] = node.get('name')
                    profile['device_capabilities'] = dict(node.find('capabilities').attrib) if node.find('capabilities') is not None else {}
                    # Optional future model overrides are intentionally not
                    # fabricated from Qt widget definitions.
                    break
            return profile
        # A configured mixer without an XML profile uses generic discovery,
        # not a potentially incorrect family guessed from control names.
        return {}

    profiles = []
    for path in sorted(ROOT.glob('*/common.xml')):
        try:
            profiles.append(_common(path))
        except (ET.ParseError, ValueError, KeyError):
            continue
    # When FFADO recognizes a device but has no assigned mixer, generic
    # discovery remains available. Avoid guessing another vendor's profile.
    if identity.get('driver'):
        return {}

    for profile in profiles:
        match = profile['match']
        if match and all(device.get(key) == value for key, value in match.items()):
            profile['match_method'] = 'hardware_id'
            return profile

    observed = _observed_paths(device)
    if not observed:
        return {}
    # A path is a family signature only if it is exclusive to one family.
    owners = {}
    for profile in profiles:
        for path in profile['discovery_paths']:
            if path and '%' not in path and path.count('/') >= 2:
                owners.setdefault(path, set()).add(profile['family'])
    candidates = []
    for profile in profiles:
        unique = {p for p in profile['discovery_paths']
                  if owners.get(p) == {profile['family']}}
        hits = unique & observed
        if len(hits) >= 2:
            candidates.append((len(hits), profile))
    candidates.sort(key=lambda item: item[0], reverse=True)
    if candidates and (len(candidates) == 1 or candidates[0][0] > candidates[1][0]):
        profile = candidates[0][1]
        profile['match_method'] = 'unique_dbus_paths'
        return profile
    return {}


