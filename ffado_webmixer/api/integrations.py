"""Optional QjackCtl actions and external-browser launches for the desktop window."""
import webbrowser
from flask import jsonify, request
from .. import qjackctl


def register(app, config, mixer_url):
    @app.get("/api/qjackctl/status")
    def qjackctl_status():
        if not config.settings.get("enable_qjackctl", False):
            return jsonify(enabled=False, running=False)
        return jsonify(enabled=True, running=qjackctl.is_running())

    @app.post("/api/qjackctl")
    def open_qjackctl():
        if not config.settings.get("enable_qjackctl", False):
            return jsonify(error="QjackCtl support is disabled in General settings"), 403
        window = request.get_json(force=True).get("window")
        try:
            qjackctl.open_window(window)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except qjackctl.QjackCtlError as exc:
            return jsonify(error=str(exc)), 503
        return jsonify(ok=True)

    @app.post("/api/open-github")
    def open_github():
        if not webbrowser.open("https://github.com/Sokoloft/ffado-webmixer"):
            return jsonify(error="Could not launch the default browser"), 503
        return jsonify(ok=True)

    @app.post("/api/open-mixer")
    def open_mixer():
        # The URL is built by the server, never accepted from the browser.
        if not webbrowser.open(mixer_url()):
            return jsonify(error="Could not launch the default browser"), 503
        return jsonify(ok=True)
