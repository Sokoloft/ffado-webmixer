from pathlib import Path
from ..themes import theme_path, available_themes

from flask import jsonify, request


def register(app, config, broadcast):
    @app.get("/api/layout")
    def get_layout():
        mix = request.args.get("mix", 0, type=int)

        return jsonify(config.layout_for(mix))

    @app.post("/api/layout")
    def set_layout():
        mix = request.args.get("mix", 0, type=int)

        incoming = [
            {
                "id": entry["id"],
                "pinned": bool(entry.get("pinned", True)),
                "minimized": bool(entry.get("minimized", False)),
            }
            for entry in request.get_json(force=True)
            if isinstance(entry.get("id"), str)
        ]

        ids = {entry["id"] for entry in incoming}

        # Channels hidden right now keep their saved config.
        config.layouts[str(mix)] = (
            incoming
            + [
                entry
                for entry in config.layout_for(mix)
                if entry["id"] not in ids
            ]
        )

        config.save()

        broadcast({"type": "layout", "mix": mix})

        return jsonify(ok=True)

    @app.get("/api/themes")
    def get_themes():
        return jsonify(available_themes())

    @app.get("/api/settings")
    def get_settings():
        return jsonify(config.settings)

    @app.post("/api/settings")
    def set_settings():
        msg = request.get_json(force=True)

        if "hide_minimized" in msg:
            config.settings["hide_minimized"] = bool(
                msg["hide_minimized"]
            )

        if "enable_qjackctl" in msg:
            if not isinstance(msg["enable_qjackctl"], bool):
                return jsonify(ok=False, error="enable_qjackctl must be a boolean"), 400
            config.settings["enable_qjackctl"] = msg["enable_qjackctl"]

        if "skip_loading_screen" in msg:
            config.settings["skip_loading_screen"] = bool(msg["skip_loading_screen"])

        if "mix" in msg:
            config.settings["mix"] = int(msg["mix"])

        if "output" in msg:
            config.settings["output"] = str(msg["output"])

        if "side_width" in msg:
            config.settings["side_width"] = max(0, int(msg["side_width"]))

        if "theme" in msg:
            theme = msg["theme"]
            # Accept any installed theme, without hardcoding its name.
            if (not isinstance(theme, str) or not theme
                    or Path(theme).name != theme
                    or theme_path(theme) is None):
                return jsonify(ok=False, error="Unknown theme"), 400
            config.settings["theme"] = theme

        if "accent_overrides" in msg:
            import re
            overrides = msg["accent_overrides"]
            if not isinstance(overrides, dict):
                return jsonify(ok=False, error="Invalid accent overrides"), 400
            clean = {}
            for name, color in overrides.items():
                if (not isinstance(name, str) or not name
                        or Path(name).name != name
                        or theme_path(name) is None
                        or not isinstance(color, str)
                        or not re.fullmatch(r"#[0-9a-fA-F]{6}", color)):
                    return jsonify(ok=False, error="Invalid accent color"), 400
                clean[name] = color.lower()
            config.settings["accent_overrides"] = clean

        config.save()

        return jsonify(ok=True)
