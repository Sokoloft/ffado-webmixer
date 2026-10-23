"""A single theme-derived FFADO logo for favicons and native Qt icons.

The splash artwork uses CSS variables; native window icons cannot. Render
those same bars with the resolved theme colors without changing Qt/FFADO.
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

from .themes import theme_path, BUILTIN_THEMES

DEFAULT_COLORS = {
    'sidebar-background': '#24272d',
    'pin-color': '#4c9fd6',
    'accent-color': '#35d4e8',
    'fader-value-color': '#f0b44c',
    'text-primary': '#e8e4da',
}
COLOR = re.compile(r'#[0-9a-fA-F]{6}\Z')
CSS_TOKEN = re.compile(r'--([a-zA-Z][a-zA-Z0-9-]*):\s*([^;{}]+);')


def valid_accent(value):
    return isinstance(value, str) and bool(COLOR.fullmatch(value))


def theme_colors(name='dark', accent=None):
    path = theme_path(name)
    if path is None:
        path = theme_path('dark')
    tokens = dict(CSS_TOKEN.findall(path.read_text(encoding='utf-8', errors='replace'))) if path else {}

    def resolve(key, depth=0):
        raw = tokens.get(key, DEFAULT_COLORS.get(key, '')).strip()
        if raw.startswith('var(') and raw.endswith(')') and depth < 5:
            name = raw[4:-1].strip()
            if name.startswith('--'):
                return resolve(name[2:], depth + 1)
        return raw if valid_accent(raw) else DEFAULT_COLORS.get(key, '#17191d')

    colors = {key: resolve(key) for key in DEFAULT_COLORS}
    if valid_accent(accent):
        # Exactly like setMixerAccent() on the loading screen.
        colors['pin-color'] = colors['accent-color'] = accent.lower()
    return colors


def themed_icon_svg(name='dark', accent=None):
    """Same eight rectangles as loading.html's inline SVG, with a themed tile."""
    c = theme_colors(name, accent)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="128" height="128" fill="none">\n'
            f'  <rect width="32" height="32" rx="4" fill="{c["sidebar-background"]}"/>\n'
            f'  <rect x="5" y="5" width="4" height="22" rx="2" fill="{c["pin-color"]}"/>\n'
            f'  <rect x="14" y="9" width="4" height="14" rx="2" fill="{c["accent-color"]}"/>\n'
            f'  <rect x="23" y="3" width="4" height="26" rx="2" fill="{c["fader-value-color"]}"/>\n'
            f'  <rect x="3" y="13" width="8" height="3" rx="1.5" fill="{c["text-primary"]}"/>\n'
            f'  <rect x="12" y="7" width="8" height="3" rx="1.5" fill="{c["text-primary"]}"/>\n'
            f'  <rect x="21" y="18" width="8" height="3" rx="1.5" fill="{c["text-primary"]}"/>\n'
            '</svg>\n')


def icon_file(theme='dark', accent=None, cache_dir=None):
    """Create a versioned icon filename; no stale cached icon after CSS edits."""
    # Built-in theme icons ship with the wheel; never write to site-packages.
    # Custom CSS themes and custom accents still use the race-safe user cache.
    if cache_dir is None and not valid_accent(accent) and theme_path(theme) == BUILTIN_THEMES / (str(theme) + '.css'):
        bundled = BUILTIN_THEMES / 'icons' / (str(theme) + '.svg')
        if bundled.is_file():
            return bundled
    svg = themed_icon_svg(theme, accent)
    digest = hashlib.sha256(svg.encode('utf-8')).hexdigest()[:20]
    directory = Path(cache_dir) if cache_dir is not None else Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'ffado-webmixer' / 'icons'
    path = directory / f'{digest}.svg'
    if not path.is_file():
        directory.mkdir(parents=True, exist_ok=True)
        # pywebview invokes JS API methods on worker threads. A PID-based
        # temporary filename is shared by *all* threads, so concurrent theme
        # updates can move the same file twice (FileNotFoundError). mkstemp
        # supplies a unique filename for every writer, including other processes.
        fd, tmp_name = tempfile.mkstemp(prefix=f'.{digest}.', suffix='.tmp', dir=directory)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as temp:
                temp.write(svg)
            # Readers always see a complete SVG, even if multiple requests
            # generate exactly the same icon at the same time.
            os.replace(tmp_name, path)
        finally:
            Path(tmp_name).unlink(missing_ok=True)
    return path


def configured_theme_icon(settings, cache_dir=None):
    theme = settings.get('theme', 'dark')
    overrides = settings.get('accent_overrides', {})
    accent = overrides.get(theme) if isinstance(overrides, dict) else None
    return icon_file(theme, accent, cache_dir)
