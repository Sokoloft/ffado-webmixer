# Theme files

Each theme is a standalone CSS file defining the same variables used by both `index.css` and `loading.css`.

- `dark.css` — Classic Dark (default)
- `midnight.css` — Midnight Blue
- `light.css` — Light
- `nordic.css` — Nordic

`themes.js` selects the stylesheet using the saved preference (mixer) or the theme query parameter (pywebview loading screen).

To add a theme, create `assets/themes/<name>.css` with all tokens, add its name to `AVAILABLE_THEMES` in `themes.js`, and add an option in `index.html`.

Delete the obsolete `ffado_webmixer/static/theme.css` (if still present from an older installation) after copying these files.
