"""Flask application assembly; route handlers live in api/."""
import socket
from flask import Flask, jsonify, request, send_from_directory, send_file, session
from .themes import theme_path
from .services.events import Hub
from .api import mixer as mixer_routes, settings as settings_routes, events as event_routes, integrations as integration_routes, stereo as stereo_routes

HOST = "0.0.0.0"
PORT = 5000

def lan_ip():
    """Best guess at this machine's address on the local network."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        sock.connect(("10.255.255.255", 1))     # UDP connect: nothing is sent
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()

def create_app(backend, description, config, about=None, device_manager=None):
    about = about or {}
    app = Flask(__name__, static_folder="assets/static", static_url_path="/static")
    hub = Hub()
    if device_manager:
        import secrets
        app.secret_key = secrets.token_hex(32)

    def broadcast(event):
        event['device'] = device_manager.current_guid if device_manager else None
        hub.publish(event, request.headers.get("X-Client-Id", ""))

    @app.get('/api/devices')
    def devices():
        return jsonify({'selected': device_manager.current_guid,
                        'devices': device_manager.list_devices()}) if device_manager else jsonify({'devices': []})

    @app.post('/api/device')
    def select_device():
        if not device_manager:
            return jsonify(error='Device switching unavailable'), 400
        guid = str((request.get_json(silent=True) or {}).get('guid', ''))
        if guid not in device_manager.devices:
            return jsonify(error='Unknown FFADO device'), 400
        session['ffado_device'] = guid
        return jsonify(ok=True, selected=guid)

    @app.post('/api/device-alias')
    def device_alias():
        if not device_manager:
            return jsonify(error='No device manager'), 400
        name=str((request.get_json(silent=True) or {}).get('name','')).strip()[:48]
        config.settings['device_alias'] = name
        config.save()
        return jsonify(ok=True)


    @app.before_request
    def reject_stale_device_write():
        # An old browser tab or an in-flight fader throttle must not suddenly
        # write to a *different* FireWire unit after device switching.
        if not device_manager or not request.path.startswith('/api/'):
            return None
        # The initial discovery endpoints are intentionally device-independent.
        if request.path in ('/api/devices', '/api/device'):
            return None
        expected = request.headers.get('X-FFADO-Device')
        if expected and expected != device_manager.current_guid:
            return jsonify(error='Selected mixer changed in another tab; reload this page'), 409
        return None

    @app.after_request
    def no_cache(response):
        """Always serve the freshest UI."""
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/favicon.svg")
    def favicon():
        return send_from_directory(app.root_path + "/assets", "icon.svg", mimetype="image/svg+xml")

    @app.get("/themes/<path:filename>")
    def theme_file(filename):
        if not filename.endswith(".css"):
            return ("Not found", 404)
        path = theme_path(filename[:-4])
        return send_file(path, mimetype="text/css") if path else ("Not found", 404)

    @app.get("/api/about")
    def get_about():
        return jsonify(
            {
                "name": about.get("name", "Mixer"),
                "version": str(about.get("version", "")),
                "mode": about.get("mode", ""),
                "device": backend.describe().get("device", ""),
                "address": f"http://{lan_ip()}:{PORT}",
            }
        )

    mixer_routes.register(app, backend, description, config, broadcast)
    settings_routes.register(app, config, broadcast)
    event_routes.register(app, hub, device_manager)
    integration_routes.register(app, config, lambda: f"http://{lan_ip()}:{PORT}/",
                                debug=bool(device_manager and device_manager.debug))
    stereo_routes.register(app, backend, description, config, broadcast)
    return app

def run_server(app):

    app.run(
        host=HOST,
        port=PORT,
        debug=False,
        use_reloader=False,
    )
