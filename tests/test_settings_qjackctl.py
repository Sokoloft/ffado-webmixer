"""Regression checks for opt-in QjackCtl and browser-opening UI."""
import importlib
import sys
import types
from pathlib import Path
from html.parser import HTMLParser

from ffado_webmixer.config import Config


class SettingsHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = {}
        self.stack = []

    def handle_starttag(self, tag, attrs):
        props = dict(attrs)
        if "id" in props:
            assert props["id"] not in self.ids, f"Duplicate HTML id: {props['id']}"
            self.ids[props["id"]] = (tag, props)


def test_settings_controls_and_placement():
    path = Path(__file__).resolve().parents[1] / "src/ffado_webmixer/assets/static/index.html"
    html = path.read_text()
    parser = SettingsHTML()
    parser.feed(html)
    assert parser.ids["enableQjackctl"][1]["type"] == "checkbox"
    assert "hidden" in parser.ids["tab-qjackctl"][1]
    assert "hidden" in parser.ids["pane-qjackctl"][1]
    assert parser.ids["aboutOpenMixer"][1]["target"] == "_blank"
    assert parser.ids["aboutOpenMixer"][1]["rel"] == "noopener noreferrer"
    general = html.split('<div class="pane" id="pane-general"', 1)[1].split('<div class="pane off" id="pane-qjackctl"', 1)[0]
    qjackctl = html.split('<div class="pane off" id="pane-qjackctl"', 1)[1].split('<div class="pane off" id="pane-theme"', 1)[0]
    assert "id=\"enableQjackctl\"" in general
    assert "id=\"jackButtons\"" not in general
    assert "id=\"jackButtons\"" in qjackctl


def test_qjackctl_preference_persists(tmp_path):
    config_path = tmp_path / 'config.json'
    config = Config(config_path)
    config.load()
    assert config.settings["enable_qjackctl"] is False
    config.settings["enable_qjackctl"] = True
    config.save()
    reread = Config(config_path)
    reread.load()
    assert reread.settings["enable_qjackctl"] is True


def test_qjackctl_is_disabled_on_server_until_enabled(monkeypatch):
    # Stub Flask's thin route decorators; no hardware, Flask installation, or HTTP listener needed.
    flask_stub = types.ModuleType("flask")
    body = {'payload': {"window": "graph"}}
    request = types.SimpleNamespace(get_json=lambda force=False: body['payload'])
    flask_stub.request = request
    flask_stub.jsonify = lambda **data: data
    monkeypatch.setitem(sys.modules, "flask", flask_stub)
    sys.modules.pop("ffado_webmixer.api.integrations", None)
    integrations = importlib.import_module("ffado_webmixer.api.integrations")

    routes = {}
    class App:
        def get(self, path):
            return lambda f: routes.setdefault(("GET", path), f) and f
        def post(self, path):
            return lambda f: routes.setdefault(("POST", path), f) and f

    config = Config()
    seen = []
    monkeypatch.setattr(integrations.qjackctl, "is_running", lambda: seen.append("check") or True)
    monkeypatch.setattr(integrations.qjackctl, "open_window", lambda w: seen.append(w))
    monkeypatch.setattr(integrations.webbrowser, "open", lambda url: seen.append(url) or True)
    integrations.register(App(), config, lambda: "http://192.168.1.2:5000/")

    assert routes[("GET", "/api/qjackctl/status")]() == {"enabled": False, "running": False}
    disabled_result, status = routes[("POST", "/api/qjackctl")]()
    assert status == 403 and "disabled" in disabled_result["error"]
    assert seen == []

    config.settings["enable_qjackctl"] = True
    assert routes[("GET", "/api/qjackctl/status")]() == {"enabled": True, "running": True}
    assert routes[("POST", "/api/qjackctl")]() == {"ok": True}
    assert seen == ["check", "graph"]
    for invalid in (None, [], {'window': 1}):
        body['payload'] = invalid
        result, code = routes[("POST", "/api/qjackctl")]()
        assert code == 400
        assert 'string' in result['error']
        assert seen == ['check', 'graph']

    assert routes[("POST", "/api/open-mixer")]() == {"ok": True}
    assert seen[-1] == "http://192.168.1.2:5000/"
    # Ensure the generated URL is used, not a caller-controlled request body.
    sys.modules.pop("ffado_webmixer.api.integrations", None)
