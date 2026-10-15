# User themes

Add custom `.css` files to `~/.config/ffado-webmixer/themes/`.
The filename (without `.css`) becomes the theme identifier and appears in the Theme dropdown.
The server scans the directory whenever `/api/themes` is requested. Refresh the mixer after adding a theme.
A user theme with the same filename as a built-in theme takes precedence.
Theme files should define the same CSS custom properties as the built-in themes in `assets/themes/`.

Preferences are stored at `~/.config/ffado-webmixer/config.json`.
On first run, an existing project-root `config.json` is imported, but left untouched.
