"""Persist ffado-webmixer preferences only; FFADO hardware is discovered live."""
import json
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

        self.settings = dict(DEFAULT_SETTINGS)

        # Names given to channels and outputs in the web UI (channel id, or "out:<id>" -> name).
        self.names = {}

        # Stereo pairs [[left, right], ...]. Global: a pair is the same on every bus.
        self.stereo = []

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
        self.stereo[:] = saved.get("stereo", [])
        self.layouts.update(saved.get("layouts", {}))
        self.legacy_layout = saved.get("layout", [])
        self.mute_memory.update(saved.get("mute_memory", {}))

        if migrated:
            self.save()
            print(f"Imported settings from {source} to {self.path}")

    def save(self):
        if self.path is None:
            return

        data = {
            "settings": self.settings,
            "names": self.names,
            "stereo": self.stereo,
            "layouts": self.layouts,
            "mute_memory": self.mute_memory,
        }

        if self.legacy_layout:
            data["layout"] = self.legacy_layout


        # Write to a temporary file first so an interrupted save can't leave a half-written config.
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

    # ---------- stereo pairs (global) ----------
    def pair_of(self, strip):
        """[left, right] if this channel is in a stereo pair, else None."""
        for pair in self.stereo:
            if strip in pair:
                return pair

        return None

    def partner_of(self, strip):
        pair = self.pair_of(strip)

        if pair is None:
            return None

        return pair[1] if strip == pair[0] else pair[0]

    def link(self, left, right):
        self.stereo.append([left, right])

    def unlink(self, strip):
        self.stereo[:] = [pair for pair in self.stereo if strip not in pair]

    def place_pair_in_layout(self, mix, left, right, target):
        """After linking: the pair takes the slot of the strip it was dropped on (in this bus's layout)."""
        entries = [dict(entry) for entry in self.layout_for(mix)]
        ids = [entry["id"] for entry in entries]

        if target not in ids:
            return

        slot = entries[ids.index(target)]
        merged = []

        for entry in entries:
            if entry["id"] == target:
                merged.append({"id": left, "pinned": slot["pinned"], "minimized": False})
            elif entry["id"] not in (left, right):
                merged.append(entry)

        self.layouts[str(mix)] = merged

    def spread_unlinked(self, left, right):
        """After unlinking: the right channel goes back to sitting directly after the left one, on every bus."""
        for key, entries in self.layouts.items():
            ids = [entry["id"] for entry in entries]

            if left not in ids:
                continue

            slot = entries[ids.index(left)]
            rebuilt = []

            for entry in entries:
                if entry["id"] == right:
                    continue

                rebuilt.append(entry)

                if entry["id"] == left:
                    rebuilt.append({"id": right, "pinned": slot["pinned"], "minimized": False})

            self.layouts[key] = rebuilt
