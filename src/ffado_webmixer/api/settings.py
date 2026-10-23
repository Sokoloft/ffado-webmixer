"""Layout and preference endpoints, with validated, serialized updates."""
import re
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from pathlib import Path

from flask import jsonify, request

from ..themes import theme_path, available_themes


_APPLICATION_PREFERENCES = ('skip_loading_screen', 'theme', 'accent_overrides')


@contextmanager
def _locked_configs(*configs):
    """Lock the whole read/modify/write operation, not just Config.save().

    A per-device preference update can also touch the global splash config.
    Acquiring locks in consistent order prevents two browser tabs for different
    devices from deadlocking while editing their shared startup preferences.
    """
    locks = {id(conf._save_lock): conf._save_lock for conf in configs if conf is not None}
    with ExitStack() as stack:
        for lock in (locks[key] for key in sorted(locks)):
            stack.enter_context(lock)
        yield


def _nonnegative_int(value, label):
    # bool is an int subclass, but it must never be accepted as a bus/width.
    if isinstance(value, bool) or not (
        isinstance(value, int) or (isinstance(value, str) and value.isascii() and value.isdecimal())
    ):
        raise ValueError(f"{label} must be a non-negative integer")
    number = int(value)
    if number < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return number


def _mix_arg():
    return _nonnegative_int(request.args.get('mix', '0'), 'mix')


def _validate_layout(payload):
    if not isinstance(payload, list):
        raise ValueError('Layout must be a list of channel entries')
    incoming, seen = [], set()
    for entry in payload:
        if not isinstance(entry, dict):
            raise ValueError('Each layout entry must be an object')
        channel = entry.get('id')
        if not isinstance(channel, str) or not channel.strip():
            raise ValueError('Each layout entry needs a non-empty channel id')
        if channel in seen:
            raise ValueError('Duplicate channel id in layout')
        pinned = entry.get('pinned', True)
        minimized = entry.get('minimized', False)
        if not isinstance(pinned, bool) or not isinstance(minimized, bool):
            raise ValueError('Layout pinned and minimized must be booleans')
        seen.add(channel)
        incoming.append({'id': channel, 'pinned': pinned, 'minimized': minimized})
    return incoming, seen


def _validate_settings(msg):
    if not isinstance(msg, dict):
        raise ValueError('Settings must be a JSON object')
    clean = {}
    for key in ('hide_minimized', 'hide_minimized_buses', 'enable_qjackctl', 'skip_loading_screen'):
        if key in msg:
            if not isinstance(msg[key], bool):
                raise ValueError(f'{key} must be a boolean')
            clean[key] = msg[key]
    for key in ('mix', 'side_width'):
        if key in msg:
            clean[key] = _nonnegative_int(msg[key], key)
    if 'output' in msg:
        if not isinstance(msg['output'], str):
            raise ValueError('output must be a string')
        clean['output'] = msg['output']
    if 'theme' in msg:
        theme = msg['theme']
        if (not isinstance(theme, str) or not theme
                or Path(theme).name != theme or theme_path(theme) is None):
            raise ValueError('Unknown theme')
        clean['theme'] = theme
    if 'accent_overrides' in msg:
        overrides = msg['accent_overrides']
        if not isinstance(overrides, dict):
            raise ValueError('Invalid accent overrides')
        colors = {}
        for name, color in overrides.items():
            if (not isinstance(name, str) or not name
                    or Path(name).name != name or theme_path(name) is None
                    or not isinstance(color, str)
                    or not re.fullmatch(r'#[0-9a-fA-F]{6}', color)):
                raise ValueError('Invalid accent color')
            colors[name] = color.lower()
        clean['accent_overrides'] = colors
    return clean


def register(app, config, broadcast, startup_config=None, bus_count=None):
    @app.get('/api/layout')
    def get_layout():
        try:
            mix = _mix_arg()
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        with _locked_configs(config):
            return jsonify(deepcopy(config.layout_for(mix)))

    @app.post('/api/layout')
    def set_layout():
        try:
            mix = _mix_arg()
            incoming, ids = _validate_layout(request.get_json(force=True))
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        key = str(mix)
        with _locked_configs(config):
            # Keep hidden channels' layouts, but never publish a half-validated
            # or half-saved layout to other browser tabs.
            previous = deepcopy(config.layout_for(mix))
            original = deepcopy(config.layouts[key]) if key in config.layouts else None
            config.layouts[key] = incoming + [
                deepcopy(entry) for entry in previous
                if entry['id'] not in ids
            ]
            try:
                config.save()
            except Exception as exc:
                if original is None:
                    config.layouts.pop(key, None)
                else:
                    config.layouts[key] = original
                try:
                    config.save()
                except Exception:
                    return jsonify(ok=False, error='Could not save layout; rollback may be incomplete'), 500
                return jsonify(ok=False, error=f'Could not save layout: {exc}'), 500
        broadcast({'type': 'layout', 'mix': mix})
        return jsonify(ok=True)

    @app.get('/api/bus-layout')
    def get_bus_layout():
        with _locked_configs(config):
            return jsonify(deepcopy(config.bus_layout))

    @app.post('/api/bus-layout')
    def set_bus_layout():
        try:
            incoming, _ = _validate_layout(request.get_json(force=True))
            if any(not entry['id'].isascii() or not entry['id'].isdecimal()
                   or str(int(entry['id'])) != entry['id']
                   or (bus_count is not None and int(entry['id']) >= bus_count())
                   for entry in incoming):
                raise ValueError('Bus ids must refer to available, numeric bus indices')
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        with _locked_configs(config):
            original = deepcopy(config.bus_layout)
            config.bus_layout = incoming + [deepcopy(entry) for entry in original
                                            if entry['id'] not in {item['id'] for item in incoming}]
            try:
                config.save()
            except Exception as exc:
                config.bus_layout = original
                try:
                    config.save()
                except Exception:
                    return jsonify(ok=False, error='Could not save bus layout; rollback may be incomplete'), 500
                return jsonify(ok=False, error=f'Could not save bus layout: {exc}'), 500
        broadcast({'type': 'bus-layout'})
        return jsonify(ok=True)

    @app.get('/api/themes')
    def get_themes():
        return jsonify(available_themes())

    @app.get('/api/settings')
    def get_settings():
        # Window appearance and the loading screen use the global preferences,
        # including when a device file still contains older saved values.
        with _locked_configs(config, startup_config):
            settings = deepcopy(config.settings)
            if startup_config is not None:
                for key in _APPLICATION_PREFERENCES:
                    settings[key] = deepcopy(startup_config.settings[key])
        return jsonify(settings)

    @app.post('/api/settings')
    def set_settings():
        try:
            changes = _validate_settings(request.get_json(force=True))
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

        startup_keys = _APPLICATION_PREFERENCES
        update_global = startup_config is not None and any(k in changes for k in startup_keys)
        with _locked_configs(config, startup_config if update_global else None):
            old_device = deepcopy(config.settings)
            old_global = deepcopy(startup_config.settings) if update_global else None
            config.settings.update(deepcopy(changes))
            if update_global:
                for key in startup_keys:
                    if key in changes:
                        startup_config.settings[key] = deepcopy(changes[key])
                startup_config.settings['_startup_preferences_migrated'] = True

            attempted = []
            try:
                # Both configurations are covered by the same transaction lock.
                # Files are replaced atomically; on a later failure, restore
                # the earlier snapshot as well as the in-memory state.
                attempted.append(config)
                config.save()
                if update_global and startup_config is not config:
                    attempted.append(startup_config)
                    startup_config.save()
            except Exception as exc:
                config.settings.clear()
                config.settings.update(old_device)
                if update_global:
                    startup_config.settings.clear()
                    startup_config.settings.update(old_global)
                failed_rollback = False
                for item in reversed(attempted):
                    try:
                        item.save()
                    except Exception:
                        failed_rollback = True
                if failed_rollback:
                    return jsonify(ok=False, error='Could not save settings; rollback may be incomplete'), 500
                return jsonify(ok=False, error=f'Could not save settings: {exc}'), 500
        return jsonify(ok=True)
