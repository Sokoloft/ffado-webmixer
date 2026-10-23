"""Resolve models with the exact FFADO configuration device definitions.

Source snapshot is bundled for offline reproducibility; installed/user entries
can override it. D-Bus matrices are not used to guess hardware identity.
"""
import logging
import shlex
import re
from pathlib import Path

LOG = logging.getLogger(__name__)
SYSTEM_CONFIG = Path('/usr/share/libffado/configuration')
BUNDLED_CONFIG = Path(__file__).parent / 'profiles' / 'ffado_configuration'
USER_CONFIG = Path('~/.ffado/configuration')


def parse_configuration(path):
    """Read FFADO's device_definitions syntax without evaluating arbitrary code."""
    path = Path(path).expanduser()
    if not path.is_file():
        return []
    source = '\n'.join(line.split('//', 1)[0] for line in path.read_text(encoding='utf-8').splitlines())
    lexer = shlex.shlex(source, posix=True,
                        punctuation_chars='{}()=;,')
    lexer.whitespace_split = True
    lexer.commenters = '#'
    tokens = [part for token in lexer for part in (re.findall(r"[{}()=;,]|[^{}()=;,]+", token) if token and token[0] in "{}()=;," else [token])]
    pos = 0

    def parse_value():
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError('Unexpected end of FFADO configuration')
        token = tokens[pos]
        pos += 1
        if token in ('{', '('):
            closing = '}' if token == '{' else ')'
            entries = []
            while pos < len(tokens) and tokens[pos] != closing:
                if tokens[pos] in (',', ';'):
                    pos += 1
                    continue
                entries.append(parse_assignment() if token == '{' else parse_value())
            if pos >= len(tokens):
                raise ValueError('Unclosed FFADO configuration block')
            pos += 1
            return dict(entries) if token == '{' else entries
        return token

    def parse_assignment():
        nonlocal pos
        key = tokens[pos]
        pos += 1
        if pos >= len(tokens) or tokens[pos] != '=':
            raise ValueError(f'Expected = after {key!r}')
        pos += 1
        value = parse_value()
        if pos < len(tokens) and tokens[pos] in (';', ','):
            pos += 1
        return key, value

    config = {}
    while pos < len(tokens):
        if tokens[pos] in (';', ','):
            pos += 1
        else:
            key, value = parse_assignment()
            config[key] = value
    return config.get('device_definitions', [])


def configured_devices(system_path=SYSTEM_CONFIG, user_path=USER_CONFIG):
    """Apply per-user definitions over system definitions, like FFADO DeviceList."""
    devices = {}
    for path in (BUNDLED_CONFIG, system_path, user_path):
        try:
            definitions = parse_configuration(path)
        except (OSError, ValueError) as exc:
            LOG.warning('Unable to parse FFADO configuration %s: %s', path, exc)
            continue
        for entry in definitions:
            try:
                key = (int(entry['vendorid'], 0), int(entry['modelid'], 0))
            except (KeyError, ValueError, TypeError):
                continue
            devices.setdefault(key, {}).update(entry)
    return devices


def resolve_device(device, definitions=None):
    """Match exactly as panelmanager.py does, including MOTU/RME overrides."""
    vendor = int(device.get('vendor_id', 0))
    model = int(device.get('model_id', 0))
    unit = device.get('unit_version')
    if vendor == 0x1f2 and unit is not None:
        model = 1 if int(unit) >= 0x15 else 0
    elif vendor == 0xa35 and unit is not None:
        model = int(unit)
    definitions = definitions if definitions is not None else configured_devices()
    entry = definitions.get((vendor, model), {})
    return {
        'mixer_name': entry.get('mixer'),
        'driver': entry.get('driver'),
        'vendor_name': entry.get('vendorname', device.get('vendor_name')),
        'model_name': entry.get('modelname', device.get('model_name')),
        'configuration_model_id': model,
        'configured': bool(entry),
    }
