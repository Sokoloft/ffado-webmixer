"""Persist ffado-webmixer preferences only; FFADO hardware is discovered live."""
import json
from copy import deepcopy
import math
import re
import threading
from pathlib import Path

DEFAULT_SETTINGS = {
    "desktop_integration_prompted": False,
    "hide_minimized": False,
    "hide_minimized_buses": False,
    "skip_loading_screen": False,
    "enable_qjackctl": False,
    "last_device_guid": None,  # last selected physical mixer; session selections remain per browser
    "mix": 0,
    "output": "",
    "side_width": 0,
    "window_size": {"width": 1180, "height": 800},
    "theme": "dark",
    "accent_overrides": {},
}


def _object(value, label):
    if not isinstance(value, dict):
        raise ValueError(f'{label} must be an object')
    return value


def _list(value, label):
    if not isinstance(value, list):
        raise ValueError(f'{label} must be a list')
    return value


def _nonnegative_int(value, label):
    # Keep numeric strings from older preferences, but never accept booleans.
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        value = int(value)
    if type(value) is not int or value < 0:
        raise ValueError(f'{label} must be a non-negative integer')
    return value


def _theme_name(value):
    # A custom theme may be temporarily unavailable; retain its safe filename.
    return (isinstance(value, str) and value not in ('', '.', '..')
            and '\0' not in value and '\\' not in value and Path(value).name == value)


def _settings(value):
    settings = deepcopy(_object(value, 'settings'))
    for key in ('desktop_integration_prompted', 'hide_minimized', 'hide_minimized_buses',
                'skip_loading_screen', 'enable_qjackctl', '_startup_preferences_migrated'):
        if key in settings and not isinstance(settings[key], bool):
            raise ValueError(f'{key} must be a boolean')
    for key in ('mix', 'side_width'):
        if key in settings:
            settings[key] = _nonnegative_int(settings[key], key)
    if 'stereo_buses' in settings:
        buses = _list(settings['stereo_buses'], 'stereo_buses')
        if any(type(bus) is not int or bus < 0 or bus % 2 for bus in buses):
            raise ValueError('stereo_buses must contain non-negative even integer bus ids')
        if len(set(buses)) != len(buses):
            raise ValueError('stereo_buses must contain unique bus ids')
    if 'stereo_outputs' in settings:
        outputs = _list(settings['stereo_outputs'], 'stereo_outputs')
        if any(not isinstance(output, str) or not re.fullmatch(r'line/[1-9][0-9]*', output)
               or int(output.split('/')[1]) % 2 != 1 for output in outputs):
            raise ValueError('stereo_outputs must contain odd-numbered line output ids')
        if len(set(outputs)) != len(outputs):
            raise ValueError('stereo_outputs must contain unique output ids')
    for key in ('output', 'device_alias'):
        if key in settings and not isinstance(settings[key], str):
            raise ValueError(f'{key} must be a string')
    guid = settings.get('last_device_guid')
    if guid is not None and not isinstance(guid, str):
        raise ValueError('last_device_guid must be a string or null')
    if 'theme' in settings and not _theme_name(settings['theme']):
        raise ValueError('theme must be a theme filename')
    if 'accent_overrides' in settings:
        overrides = _object(settings['accent_overrides'], 'accent_overrides')
        if any(not _theme_name(name) or not isinstance(color, str)
               or not re.fullmatch(r'#[0-9a-fA-F]{6}', color)
               for name, color in overrides.items()):
            raise ValueError('accent_overrides must contain theme names and hex colors')
    if 'window_size' in settings:
        size = _object(settings['window_size'], 'window_size')
        for key in ('width', 'height'):
            if key in size and (type(size[key]) is not int or size[key] <= 0):
                raise ValueError(f'window_size {key} must be a positive integer')
        settings['window_size'] = {**DEFAULT_SETTINGS['window_size'], **size}
    # Preserve extension and migration settings that are valid JSON values.
    return {**deepcopy(DEFAULT_SETTINGS), **settings}


def _layout(value, label, buses=False):
    entries = deepcopy(_list(value, label))
    seen = set()
    for entry in entries:
        _object(entry, f'{label} entry')
        channel = entry.get('id')
        if not isinstance(channel, str) or not channel.strip() or channel in seen:
            raise ValueError(f'{label} entries need unique, non-empty ids')
        if buses and (not channel.isascii() or not channel.isdecimal()
                      or str(int(channel)) != channel):
            raise ValueError('bus_layout entries need numeric bus ids')
        for key, default in (('pinned', True), ('minimized', False)):
            if not isinstance(entry.get(key, default), bool):
                raise ValueError(f'{label} {key} must be a boolean')
        seen.add(channel)
    return entries


def _invalid_json_constant(value):
    raise ValueError(f'Invalid JSON number {value}')


def _finite_json_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('JSON numbers must be finite')
    return number


class Config:
    def __init__(self, path=None):
        # With no path (demo mode) nothing is read or written.
        self.path = Path(path) if path else None

        self.settings = deepcopy(DEFAULT_SETTINGS)
        self._save_lock = threading.RLock()
        # Serialize stereo checks and commits across simultaneous browser tabs.
        self._pair_lock = threading.RLock()

        # Names given to channels and outputs in the web UI (channel id, or "out:<id>" -> name).
        self.names = {}

        # Old configs stored one stereo pair list for every bus. Keep that as
        # a read-only fallback so existing user settings migrate without
        # losing links. New edits are always per-bus and override the fallback.
        self.stereo = []
        self.stereo_by_mix = {}

        # Strip order / pinned / minimized, kept separately for every bus (bus id -> list of entries).
        self.layouts = {}
        # Device-specific bus tab order, pin and minimized state.
        self.bus_layout = []

        # Older save files had one layout shared by all buses. Buses without their own layout start from it.
        self.legacy_layout = []

        # Main / Phones fader positions remembered while they are muted (they have no mute of their own).
        self.mute_memory = {}


    # ---------- loading and saving ----------
    def load(self, migrate_from=None):
        if self.path is None:
            return

        source = self.path
        migrated = False

        if not source.exists():
            if migrate_from and Path(migrate_from).exists():
                source = Path(migrate_from)
                migrated = True
            else:
                self.save()                  # first run: write the defaults so the file exists
                return

        try:
            saved = json.loads(source.read_text(encoding="utf-8"),
                               parse_constant=_invalid_json_constant,
                               parse_float=_finite_json_float)
            state = self._validated_state(saved)
        except (OSError, ValueError):
            if source == self.path:
                # Don't overwrite a file the user might want to repair.
                bad = self._keep_bad_file()
                print(f"{self.path.name} couldn't be read. It was kept as {bad.name} and a new one is being started.")
                self.save()
            return

        # Only publish after every collection and nested setting is validated.
        # Preserve dictionary identities held by the backend's mute recovery.
        with self._pair_lock, self._save_lock:
            for key in ('settings', 'names', 'stereo_by_mix', 'layouts', 'mute_memory'):
                target = getattr(self, key)
                target.clear()
                target.update(state[key])
            self.stereo[:] = state['stereo']
            self.bus_layout = state['bus_layout']
            self.legacy_layout = state['layout']

        if migrated:
            self.save()
            print(f"Imported settings from {source} to {self.path}")

    @classmethod
    def _validated_state(cls, saved):
        _object(saved, 'configuration')
        names = _object(saved.get('names', {}), 'names')
        if any(not isinstance(name, str) for name in names.values()):
            raise ValueError('names must contain strings')
        bus_pairs = _object(saved.get('stereo_by_mix', {}), 'stereo_by_mix')
        # Stereo lists already have a compatibility cleaner: a broken bus
        # override becomes [], retaining valid pairs saved on other buses.
        layouts = _object(saved.get('layouts', {}), 'layouts')
        clean_layouts = {}
        for mix, layout in layouts.items():
            _nonnegative_int(mix, 'layout bus')
            clean_layouts[mix] = _layout(layout, 'layout')
        memory = _object(saved.get('mute_memory', {}), 'mute_memory')
        if any(type(value) not in (int, float)
               or (isinstance(value, float) and not math.isfinite(value))
               for value in memory.values()):
            raise ValueError('mute_memory must contain finite numbers')
        return {
            'settings': _settings(saved.get('settings', {})),
            'names': names,
            'stereo': cls._clean_pairs(_list(saved.get('stereo', []), 'stereo')),
            'stereo_by_mix': {key: cls._clean_pairs(pairs) for key, pairs in bus_pairs.items()
                              if key.isascii() and key.isdecimal()},
            'layouts': clean_layouts,
            'bus_layout': _layout(saved.get('bus_layout', []), 'bus_layout', buses=True),
            'layout': _layout(saved.get('layout', []), 'layout'),
            'mute_memory': memory,
        }

    def _keep_bad_file(self):
        """Reserve a unique backup name before moving the unreadable file."""
        index = 0
        while True:
            suffix = '.bad' if index == 0 else f'.bad.{index}'
            bad = self.path.with_name(self.path.name + suffix)
            try:
                with bad.open('xb'):
                    pass
            except FileExistsError:
                index += 1
                continue
            try:
                self.path.replace(bad)
            except OSError:
                bad.unlink(missing_ok=True)
                raise
            return bad

    def save(self):
        if self.path is None:
            return
        # Flask handles browser requests concurrently. A single stable temp
        # name is safe only when writes for this config are serialized.
        with self._save_lock:
            data = {
                "settings": self.settings,
                "names": self.names,
                "stereo": self.stereo,  # old global pairs: fallback for unedited buses
                "stereo_by_mix": self.stereo_by_mix,
                "layouts": self.layouts,
                "bus_layout": self.bus_layout,
                "mute_memory": self.mute_memory,
            }
            if self.legacy_layout:
                data["layout"] = self.legacy_layout
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + ".tmp")
            temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
            temporary.replace(self.path)

    # ---------- layouts (per bus) ----------
    def layout_for(self, mix):
        """The saved layout of one bus; a bus never arranged yet inherits the old shared layout (if any)."""
        saved = self.layouts.get(str(mix))

        if saved is None:
            saved = [dict(entry) for entry in self.legacy_layout]

        return saved

    # ---------- stereo pairs (per output mix/bus) ----------
    @staticmethod
    def _clean_pairs(pairs):
        """Never let a broken/old config hide the same channel twice.

        Keep the first valid pair, including its Left -> Right ordering.  A
        malformed or overlapping later entry cannot create an inconsistent UI.
        """
        if not isinstance(pairs, list):
            return []
        cleaned, seen = [], set()
        for pair in pairs:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                continue
            left, right = pair
            if (not isinstance(left, str) or not isinstance(right, str)
                    or not left.strip() or not right.strip() or left == right
                    or left in seen or right in seen):
                continue
            cleaned.append([left, right])
            seen.update((left, right))
        return cleaned

    def pairs_for(self, mix):
        """Validated snapshot of the ordered [Left, Right] pairs on this bus.

        A legacy global list is the initial value for uncustomized buses. An
        explicit [] overrides it. Callers never mutate the underlying list.
        """
        with self._pair_lock:
            return self._clean_pairs(self.stereo_by_mix.get(str(mix), self.stereo))

    def pair_of(self, strip, mix=0):
        """Pair containing ``strip`` on one bus, or None."""
        for pair in self.pairs_for(mix):
            if strip in pair:
                return pair
        return None

    def partner_of(self, strip, mix=0):
        pair = self.pair_of(strip, mix)
        return (pair[1] if strip == pair[0] else pair[0]) if pair else None

    def link(self, left, right, mix=0):
        with self._pair_lock:
            if not isinstance(left, str) or not isinstance(right, str) or not left.strip() or not right.strip() or left == right:
                raise ValueError('Choose two different input channels')
            pairs = self.pairs_for(mix)
            if any(left in pair or right in pair for pair in pairs):
                raise ValueError('One or both channels are already in a stereo pair on this bus. Unlink first.')
            self.stereo_by_mix[str(mix)] = pairs + [[left, right]]

    def unlink(self, strip, mix=0):
        with self._pair_lock:
            pairs = self.pairs_for(mix)
            if not any(strip in pair for pair in pairs):
                raise ValueError('This channel is not in a stereo pair on this bus')
            self.stereo_by_mix[str(mix)] = [pair for pair in pairs if strip not in pair]

    def place_pair_in_layout(self, mix, left, right, target=None):
        """Pairing is visual: retain both saved layout entries, even Right.

        /api/state marks the Right channel as hidden while paired. Keeping its
        original pin, minimize and position data means unlink restores exactly
        that bus's layout, without ever changing another bus's visibility.
        """
        return None

    def spread_unlinked(self, left, right, mix=0):
        """Repair old layouts that deleted Right; touch only the active bus.

        Newly linked layouts already retain the Right channel, so their order
        and minimized/pinned settings should remain untouched after unlinking.
        """
        key = str(mix)
        entries = self.layouts.get(key)
        if entries is None:
            if not self.legacy_layout:
                return
            entries = [dict(entry) for entry in self.legacy_layout]
        ids = [entry.get('id') for entry in entries]
        if right in ids or left not in ids:
            return
        entries = [dict(entry) for entry in entries]
        index = ids.index(left)
        entries.insert(index + 1, {'id': right, 'pinned': entries[index].get('pinned', True),
                                   'minimized': False})
        self.layouts[key] = entries
