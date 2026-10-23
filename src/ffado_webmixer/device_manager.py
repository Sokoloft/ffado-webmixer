"""Per-browser device selection; hardware units keyed by FireWire GUID.

Each browser's signed session independently selects a mixer. A saved global GUID
supplies the default selection on application startup or for a new session.
HTTP requests pin their GUID, backend and configuration before validation so
another browser changing the saved default cannot redirect an in-flight write.
"""
from flask import session, has_request_context, request
from .config import Config, DEFAULT_SETTINGS
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
        self.global_config = settings
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
                    config.stereo_by_mix = deepcopy(settings.stereo_by_mix)
                    config.layouts = deepcopy(settings.layouts)
                    config.bus_layout = deepcopy(settings.bus_layout)
                    config.legacy_layout = deepcopy(settings.legacy_layout)
                    config.mute_memory = deepcopy(settings.mute_memory)
                config.save()
            self.configs[guid] = config
            backend.config = config
            backend.mute_memory = config.mute_memory
            if hasattr(backend, 'attach_mute_recovery'):
                backend.attach_mute_recovery(debug=debug)

        # Older releases saved startup preferences only in the per-GUID file,
        # but the desktop launcher read config.json. Import them once, without
        # overwriting explicit preferences already saved in config.json.
        if settings.path is not None and not settings.settings.get('_startup_preferences_migrated'):
            original = self.configs[self.order[0]].settings
            for key in ('skip_loading_screen', 'theme', 'accent_overrides'):
                if (settings.settings.get(key) == DEFAULT_SETTINGS[key]
                        and original.get(key) != DEFAULT_SETTINGS[key]):
                    settings.settings[key] = deepcopy(original[key])
            settings.settings['_startup_preferences_migrated'] = True
            settings.save()

    @property
    def preferred_guid(self):
        """Use the last chosen physical device if it is still connected.

        A FireWire GUID is stable across discovery-order changes. Do not remove
        an absent device's preference: reconnecting it should restore it.
        """
        guid = self.global_config.settings.get('last_device_guid')
        return guid if isinstance(guid, str) and guid in self.devices else self.order[0]

    @property
    def current_guid(self):
        selected = self._request_selection()
        if selected is not None:
            return selected[0]
        guid = session.get('ffado_device') if has_request_context() else None
        return guid if isinstance(guid, str) and guid in self.devices else self.preferred_guid

    def _request_selection(self):
        if has_request_context():
            selections = request.environ.get('ffado_webmixer.device_selections', {})
            return selections.get(self)
        return None

    def pin_request(self):
        """Keep one device identity and its objects for this HTTP request.

        Store on the request rather than the application context: embedded
        callers can reuse an application context across several requests.
        Repeated calls must not replace an already validated selection.
        """
        selections = request.environ.setdefault('ffado_webmixer.device_selections', {})
        if self not in selections:
            guid = self.current_guid
            selections[self] = (guid, self.devices[guid], self.configs[guid])

    def remember_device(self, guid):
        """Persist a successful device choice as the startup default.

        The browser's session is updated by the caller only after this save.
        Restore the previous value and on-disk file if a write fails even after
        replacing the destination, as with the other settings endpoints.
        """
        if not isinstance(guid, str) or guid not in self.devices:
            raise ValueError('Unknown FFADO device')
        config = self.global_config
        with config._save_lock:
            previous = config.settings.get('last_device_guid')
            if previous == guid:
                return
            config.settings['last_device_guid'] = guid
            try:
                config.save()
            except Exception:
                if previous is None:
                    config.settings.pop('last_device_guid', None)
                else:
                    config.settings['last_device_guid'] = previous
                try:
                    config.save()
                except Exception as rollback_error:
                    raise RuntimeError('Saving the preferred mixer failed; rollback may be incomplete') from rollback_error
                raise

    @property
    def backend(self):
        selected = self._request_selection()
        if selected is not None:
            return selected[1]
        return self.devices[self.current_guid]

    @property
    def config(self):
        selected = self._request_selection()
        if selected is not None:
            return selected[2]
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
