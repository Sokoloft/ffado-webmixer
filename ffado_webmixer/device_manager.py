"""Per-browser device selection; hardware units keyed by FireWire GUID.

FFADO identifies *all* devices at startup, then each model-specific profile
controls one Mixer instance. A signed Flask session selects the active instance;
there is no process-global 'currently selected mixer' to race between browsers.
"""
from flask import session, has_request_context
from .config import Config
from pathlib import Path
from copy import deepcopy
import re
from collections import Counter


class DeviceManager:
    def __init__(self, devices, settings, debug=False):
        if not devices:
            raise ValueError('No supported FFADO devices were found')
        # Never silently overwrite one physical device with another. This is
        # particularly important when several identical ProFires are connected.
        # FFADO supplies a 16-hex-digit FireWire GUID, not a discovery index.
        self.devices = {}
        for backend in devices:
            guid = str(backend.guid).lower()
            if not re.fullmatch(r'[0-9a-f]{16}', guid):
                raise ValueError(f'Invalid FireWire GUID {backend.guid!r}; cannot safely select this device')
            if guid in self.devices:
                raise ValueError(f'Duplicate FireWire GUID {guid}; refusing to merge two devices')
            self.devices[guid] = backend
        self.order = list(self.devices)
        self.configs = {}
        self.debug = debug
        for guid, backend in self.devices.items():
            # GUID is the stable settings key: discovery order changes when a
            # device is unplugged or another FireWire adapter is reconnected.
            # Previously, the first device used the global config.json. Migrate
            # its preferences once to the initial GUID profile, preserving the
            # original file for window/theme defaults and easy rollback.
            device_file = (settings.path.parent / 'devices' / f'{guid}.json') if settings.path else None
            config = Config(device_file)
            if device_file and device_file.is_file():
                config.load()
            else:
                config.settings = deepcopy(settings.settings)
                if guid == self.order[0]:
                    config.names = deepcopy(settings.names)
                    config.stereo = deepcopy(settings.stereo)
                    config.layouts = deepcopy(settings.layouts)
                    config.legacy_layout = deepcopy(settings.legacy_layout)
                    config.mute_memory = deepcopy(settings.mute_memory)
                config.save()
            self.configs[guid] = config
            backend.config = config
            backend.mute_memory = config.mute_memory
            if hasattr(backend, 'attach_mute_recovery'):
                backend.attach_mute_recovery(debug=debug)

    @property
    def current_guid(self):
        guid = session.get('ffado_device') if has_request_context() else None
        return guid if guid in self.devices else self.order[0]

    @property
    def backend(self):
        return self.devices[self.current_guid]

    @property
    def config(self):
        return self.configs[self.current_guid]

    def list_devices(self):
        """Return stable identities and distinguish otherwise identical devices.

        Some DICE hardware exposes a nickname, but identical units frequently
        use the same default name. A GUID suffix is display-only; it is never
        used to select a device or infer a mixer profile.
        """
        devices = []
        for guid, mixer in self.devices.items():
            model = mixer.describe()['device']
            alias = str(self.configs[guid].settings.get('device_alias') or '').strip()
            nickname = ''
            if mixer.nickname_path:
                try:
                    nickname = str(mixer.helper.get_value(mixer.nickname_path['path'], 'Text')).strip()
                except Exception:
                    pass
            base_name = alias or nickname or model
            devices.append({'guid': guid, 'model': model, 'name': base_name,
                            'alias': alias, 'nickname': nickname,
                            'profile': mixer.profile.get('device_profile', '')})
        repeats = Counter(d['name'] for d in devices)
        for item in devices:
            if repeats[item['name']] > 1:
                item['name'] = f"{item['name']} · {item['guid'][-6:]}"
        return devices


class SelectedBackend:
    """Resolve the selected device on each Flask request, not at route registration."""
    def __init__(self, manager): self.manager=manager
    def __getattr__(self, name): return getattr(self.manager.backend, name)
    def describe(self): return self.manager.backend.describe()


class SelectedConfig:
    def __init__(self, manager): self.manager=manager
    def __getattr__(self, name): return getattr(self.manager.config, name)
    def __setattr__(self, name, value):
        if name == 'manager': object.__setattr__(self, name, value)
        else: setattr(self.manager.config, name, value)
