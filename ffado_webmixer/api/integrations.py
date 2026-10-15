import webbrowser
from flask import jsonify, request
from .. import qjackctl

def register(app):
    @app.get("/api/qjackctl/status")
    def qjackctl_status():
        return jsonify(running=qjackctl.is_running())

    @app.post("/api/qjackctl")
    def open_qjackctl():
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
        if not webbrowser.open("https://github.com"):
            return jsonify(error="Could not launch the default browser"), 503
        return jsonify(ok=True)
