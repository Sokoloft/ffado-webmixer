# Theme files

Each theme is a standalone CSS file defining the same variables used by both `index.css` and `loading.css`.

- `breeze.css` — Breeze
- `catppuccin.css` — Catppuccin
- `dark.css` — Classic Dark (default)
- `everforest.css` — Everforest
- `gruvbox.css` — Gruvbox
- `high-contrast.css` — High Contrast
- `light.css` — Light
- `midnight.css` — Midnight Blue
- `nordic.css` — Nordic
- `tokyonight.css` — Tokyo Night

`src/ffado_webmixer/assets/static/themes.js` selects the stylesheet using the saved preference (mixer) or the theme query parameter (pywebview loading screen).

To add a theme, create `src/ffado_webmixer/assets/themes/<name>.css` with all tokens, add its name to `AVAILABLE_THEMES` in `src/ffado_webmixer/assets/static/themes.js`, and add an option in `src/ffado_webmixer/assets/static/index.html`.

Delete the obsolete `src/ffado_webmixer/assets/static/theme.css` (if still present from an older installation) after copying these files.
