"""Flask application assembly; route handlers live in api/."""
import socket
from flask import Flask, jsonify, request, send_file, session
from .themes import theme_path
from .theme_icons import themed_icon_svg, valid_accent
from .services.events import Hub
from .access import AccessPolicy, register as register_access
from .remote_access import DEFAULT_PORT
from .api import mixer as mixer_routes, settings as settings_routes, events as event_routes, integrations as integration_routes, stereo as stereo_routes

HOST = "127.0.0.1"
PORT = DEFAULT_PORT

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

def create_app(backend, description, config, about=None, device_manager=None, access_policy=None):
    about = about or {}
    app = Flask(__name__, static_folder="assets/static", static_url_path="/static")
    policy = access_policy or AccessPolicy()
    register_access(app, policy)
    hub = Hub()
    application_config = device_manager.global_config if device_manager else config

    def mixer_url():
        from ipaddress import ip_address
        address = lan_ip() if ip_address(policy.host).is_unspecified else policy.host
        if ':' in address:
            address = f'[{address}]'
        return f'http://{address}:{app.ffado_port}'
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
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get('guid'), str):
            return jsonify(error='Device selection requires a GUID string'), 400
        guid = payload['guid']
        if guid not in device_manager.devices:
            return jsonify(error='Unknown FFADO device'), 400
        try:
            device_manager.remember_device(guid)
        except Exception as exc:
            return jsonify(error=f'Could not remember selected mixer: {exc}'), 500
        session['ffado_device'] = guid
        return jsonify(ok=True, selected=guid)

    @app.post('/api/device-alias')
    def device_alias():
        if not device_manager:
            return jsonify(error='No device manager'), 400
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get('name'), str):
            return jsonify(error='Device alias must be a string'), 400
        name = payload['name'].strip()[:48]
        with config._save_lock:
            old = config.settings.get('device_alias')
            config.settings['device_alias'] = name
            try:
                config.save()
            except Exception as exc:
                if old is None:
                    config.settings.pop('device_alias', None)
                else:
                    config.settings['device_alias'] = old
                try:
                    config.save()
                except Exception:
                    return jsonify(error='Could not save device alias; rollback may be incomplete'), 500
                return jsonify(error=f'Could not save device alias: {exc}'), 500
        return jsonify(ok=True)


    @app.before_request
    def reject_stale_device_write():
        # Every route (including discovery and streams) must use the same
        # backend/configuration as its validation and eventual broadcast.
        if device_manager:
            device_manager.pin_request()
        # An old browser tab or an in-flight fader throttle must not suddenly
        # write to a *different* FireWire unit after device switching.
        if not device_manager or not request.path.startswith('/api/'):
            return None
        # The initial discovery endpoints are intentionally device-independent.
        if request.path in ('/api/devices', '/api/device', '/api/remote-access'):
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
        # A browser may be previewing a different theme from the Qt client.
        # Each request resolves its own colors and does not modify config.
        explicit_theme = 'theme' in request.args
        with application_config._save_lock:
            name = request.args.get('theme', application_config.settings.get('theme', 'dark'))
            accent = request.args.get('accent')
            if not valid_accent(accent):
                # Explicit per-browser theme requests without an accent mean
                # "use the theme default", even if another client had an override.
                # Bare /favicon.svg uses the saved global theme and accent.
                accent = None
                if not explicit_theme:
                    overrides = application_config.settings.get('accent_overrides', {})
                    accent = overrides.get(name) if isinstance(overrides, dict) else None
        return app.response_class(themed_icon_svg(name, accent), mimetype='image/svg+xml',
                                  headers={'Cache-Control': 'no-store'})

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
                "address": mixer_url(),
            }
        )

    mixer_routes.register(app, backend, description, config, broadcast)
    settings_routes.register(app, config, broadcast, bus_count=lambda: len(backend.mixes),
                             startup_config=application_config if device_manager else None)
    event_routes.register(app, hub, device_manager)
    integration_routes.register(app, config, lambda: mixer_url() + '/',
                                debug=bool(device_manager and device_manager.debug))
    stereo_routes.register(app, backend, description, config, broadcast)
    return app

def prepare_server(app):
    """Bind synchronously, before Qt is opened, so port failures are visible.

    Flask's development run() exits inside its calling thread on bind errors;
    the previous daemon-thread startup left the splash waiting indefinitely.
    Keep the same threaded request handling as Flask.run().
    """
    from werkzeug.serving import make_server
    host = getattr(app, 'ffado_host', HOST)
    port = getattr(app, 'ffado_port', PORT)
    try:
        return make_server(host, port, app, threaded=True)
    except (OSError, SystemExit) as exc:
        raise RuntimeError(
            f'Cannot start ffado-webmixer on {host}:{port} '
            '(port already in use or unavailable). Close the other server or free the port.'
        ) from exc


def run_server(app):
    """Blocking server entry point, retained for callers using headless mode."""
    server = prepare_server(app)
    try:
        server.serve_forever()
    finally:
        server.server_close()
