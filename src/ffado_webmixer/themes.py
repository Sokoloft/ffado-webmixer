"""Built-in and user CSS themes (user files override built-ins)."""
from pathlib import Path

BUILTIN_THEMES = Path(__file__).resolve().parent / "assets" / "themes"
USER_THEMES = Path.home() / ".config" / "ffado-webmixer" / "themes"

def available_themes():
    names = {p.stem for p in BUILTIN_THEMES.glob("*.css") if p.is_file()}
    names.update(p.stem for p in USER_THEMES.glob("*.css") if p.is_file())
    return sorted(names)

def theme_path(name):
    if not isinstance(name, str) or not name or Path(name).name != name or name in (".", "..") or "/" in name or "\\" in name:
        return None
    for directory in (USER_THEMES, BUILTIN_THEMES):
        path = directory / (name + ".css")
        if path.is_file():
            return path
    return None
