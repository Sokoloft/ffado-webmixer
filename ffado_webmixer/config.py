"""Persist ffado-webmixer preferences only; FFADO hardware is discovered live."""
import json
from copy import deepcopy
import threading
from pathlib import Path

DEFAULT_SETTINGS = {
    "hide_minimized": False,
    "skip_loading_screen": False,
    "enable_qjackctl": False,
    "mix": 0,
    "output": "",
    "side_width": 0,
    "window_size": {"width": 1180, "height": 800},
    "theme": "dark",
    "accent_overrides": {},
}


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
            saved = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            if source == self.path:
                # Don't overwrite a file the user might want to repair.
                bad = self.path.with_name(self.path.name + ".bad")
                self.path.replace(bad)
                print(f"{self.path.name} couldn't be read. It was kept as {bad.name} and a new one is being started.")
                self.save()
            return

        self.settings.update(saved.get("settings", {}))
        self.names.update(saved.get("names", {}))
        self.stereo[:] = self._clean_pairs(saved.get("stereo", []))
        raw_bus_pairs = saved.get("stereo_by_mix", {})
        if isinstance(raw_bus_pairs, dict):
            self.stereo_by_mix.update({str(k): self._clean_pairs(v)
                                       for k, v in raw_bus_pairs.items()
                                       if str(k).isdigit()})
        self.layouts.update(saved.get("layouts", {}))
        self.legacy_layout = saved.get("layout", [])
        self.mute_memory.update(saved.get("mute_memory", {}))

        if migrated:
            self.save()
            print(f"Imported settings from {source} to {self.path}")

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
