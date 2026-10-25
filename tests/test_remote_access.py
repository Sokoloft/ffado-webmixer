"""Remote-access persistence, CLI setup and real HTTP credential management."""
import getpass
import json
import os
import sys
import warnings
from pathlib import Path

import pytest
from flask import Flask

from ffado_webmixer.access import AccessPolicy, register
from ffado_webmixer.remote_access import RemoteAccessConfig
from test_access import authorization, PASSWORD, REMOTE


@pytest.fixture
def credentials(tmp_path):
    config = RemoteAccessConfig(tmp_path / 'ffado-webmixer' / 'auth.json')
    config.update(enabled=True, username='studio', password=PASSWORD)
    return config


@pytest.fixture
def app(credentials):
    app = Flask(__name__)
    register(app, AccessPolicy('0.0.0.0', credentials))
    app.get('/')(lambda: 'mixer')
    return app


def test_credentials_are_salted_private_and_reloadable(credentials, tmp_path):
    stored = credentials.path.read_text()
    record = json.loads(stored)
    assert PASSWORD not in stored
    assert record['username'] == 'studio'
    assert record['password_hash'].startswith('$argon2id$')
    assert credentials.path.stat().st_mode & 0o777 == 0o600
    assert credentials.path.parent.stat().st_mode & 0o777 == 0o700
    assert not list(credentials.path.parent.glob('*.tmp'))
    restored = RemoteAccessConfig(credentials.path)
    restored.load()
    assert restored.authenticate('studio', PASSWORD)
    assert not restored.authenticate('studio', 'wrong')
    assert not restored.authenticate('other', PASSWORD)
    second = RemoteAccessConfig(tmp_path / 'other.json')
    second.update(enabled=True, username='studio', password=PASSWORD)
    assert second._password_hash != record['password_hash']


@pytest.mark.parametrize('payload', [
    None, [], {}, {'enabled': 'yes', 'username': 'studio'},
    {'enabled': True, 'username': 'studio'},
    {'enabled': False, 'username': 'studio'},
    {'enabled': False, 'username': '', 'password': PASSWORD},
    {'enabled': True, 'username': 'studio', 'password': 'short'},
    {'enabled': True, 'username': 'bad:name', 'password': PASSWORD},
    {'enabled': True, 'username': 'bad\nname', 'password': PASSWORD},
    {'enabled': False, 'username': None},
    {'enabled': True, 'username': 'studio', 'password': 123},
])
def test_invalid_setup_does_not_create_a_file(tmp_path, payload):
    config = RemoteAccessConfig(tmp_path / 'auth.json')
    app = Flask(__name__)
    register(app, AccessPolicy(remote_access=config))
    # Explicit data/null keeps Flask's JSON content-type on all malformed bodies.
    response = app.test_client().post('/api/remote-access', data=json.dumps(payload),
                                      content_type='application/json')
    assert response.status_code == 400
    assert not config.path.exists()
    assert not config.enabled


def test_local_gui_setup_persists_and_does_not_return_secrets(tmp_path):
    config = RemoteAccessConfig(tmp_path / 'auth.json')
    app = Flask(__name__)
    register(app, AccessPolicy(remote_access=config))
    response = app.test_client().post('/api/remote-access', json={
        'enabled': True, 'username': 'my-mixer', 'password': PASSWORD})
    assert response.status_code == 200
    assert response.json == {'enabled': True, 'username': 'my-mixer', 'configured': True,
                             'port': 5000, 'listening_port': 5000,
                             'can_manage': True, 'listening': False, 'restart_required': True}
    assert PASSWORD not in response.text and '$argon2' not in response.text
    reloaded = RemoteAccessConfig(config.path)
    reloaded.load()
    assert reloaded.authenticate('my-mixer', PASSWORD)


def test_disabling_before_setup_saves_a_reloadable_empty_record(tmp_path):
    config = RemoteAccessConfig(tmp_path / 'auth.json')
    config.update(enabled=False, username='')
    restored = RemoteAccessConfig(config.path)
    restored.load()
    assert not restored.enabled and not restored.configured


def test_remote_clients_cannot_change_credentials(app, credentials):
    client = app.test_client()
    original = credentials.path.read_bytes()
    response = client.get('/api/remote-access', headers=authorization(), environ_overrides=REMOTE)
    assert response.status_code == 200 and not response.json['can_manage']
    assert 'password_hash' not in response.json
    response = client.post('/api/remote-access', json={
        'enabled': True, 'username': 'attacker', 'password': PASSWORD},
        headers=authorization(), environ_overrides=REMOTE)
    assert response.status_code == 403
    assert credentials.path.read_bytes() == original


def test_password_rotation_invalidates_cached_authentication_and_disable_blocks_requests(app, credentials):
    client = app.test_client()
    assert client.get('/', headers=authorization(), environ_overrides=REMOTE).status_code == 200
    new_password = 'a completely different password'
    response = client.post('/api/remote-access', json={
        'enabled': True, 'username': 'new-name', 'password': new_password})
    assert response.status_code == 200 and not response.json['restart_required']
    assert client.get('/', headers=authorization(), environ_overrides=REMOTE).status_code == 401
    new_auth = authorization(new_password, 'new-name')
    assert client.get('/', headers=new_auth, environ_overrides=REMOTE).status_code == 200
    response = client.post('/api/remote-access', json={
        'enabled': False, 'username': 'new-name', 'password': ''})
    assert response.status_code == 200 and response.json['restart_required']
    assert client.get('/', headers=new_auth, environ_overrides=REMOTE).status_code == 401
    assert client.get('/').status_code == 200
    client.post('/api/remote-access', json={'enabled': True, 'username': 'new-name'})
    assert client.get('/', headers=new_auth, environ_overrides=REMOTE).status_code == 200


def test_failed_atomic_save_keeps_disk_and_active_credentials(app, credentials, monkeypatch):
    original = credentials.path.read_bytes()
    assert credentials.authenticate('studio', PASSWORD)
    def fail(*_):
        raise OSError('disk full')
    monkeypatch.setattr(os, 'replace', fail)
    response = app.test_client().post('/api/remote-access', json={
        'enabled': True, 'username': 'changed', 'password': 'another long password'})
    assert response.status_code == 500
    assert credentials.path.read_bytes() == original
    assert credentials.authenticate('studio', PASSWORD)
    assert not list(credentials.path.parent.glob('*.tmp'))


@pytest.mark.parametrize('headers,base_url', [
    ({'Origin': 'https://evil.example'}, 'http://localhost'),
    ({'Origin': 'null'}, 'http://localhost'),
    ({'X-Forwarded-For': '127.0.0.1'}, 'http://rebound.example'),
])
def test_credential_setup_keeps_origin_and_host_guards(app, credentials, headers, base_url):
    original = credentials.path.read_bytes()
    response = app.test_client().post('/api/remote-access', json={
        'enabled': False, 'username': 'studio'}, headers=headers, base_url=base_url)
    assert response.status_code in (401, 403)
    assert credentials.path.read_bytes() == original


def test_demo_settings_are_read_only(credentials):
    config = RemoteAccessConfig(credentials.path, writable=False)
    config.load()
    app = Flask(__name__)
    register(app, AccessPolicy(remote_access=config))
    client = app.test_client()
    assert not client.get('/api/remote-access').json['can_manage']
    assert client.post('/api/remote-access', json={
        'enabled': False, 'username': 'studio'}).status_code == 403


@pytest.mark.parametrize('text', ['{', 'null', '[]', '{}',
    '{"enabled":true,"username":"studio","password_hash":"plaintext"}',
    '{"enabled":false,"username":null,"password_hash":null}'])
def test_corrupt_configuration_fails_closed(tmp_path, text):
    path = tmp_path / 'auth.json'
    path.write_text(text)
    config = RemoteAccessConfig(path)
    with pytest.raises(ValueError, match='--enable-remote-access'):
        config.load()
    assert not config.enabled


def setup_cli(monkeypatch, tmp_path, flag='--enable-remote-access'):
    from ffado_webmixer import main
    monkeypatch.setattr(main, 'CONFIG_DIR', tmp_path / 'ffado-webmixer')
    monkeypatch.setattr(main, 'CONFIG_FILE', tmp_path / 'ffado-webmixer' / 'config.json')
    monkeypatch.setattr(sys, 'argv', ['main.py', flag])
    monkeypatch.setattr(main, 'create_backends', lambda *_: pytest.fail('Must not access hardware'))
    return main


def test_cli_prompts_username_then_hidden_password_and_gui_can_read_it(tmp_path, monkeypatch, capsys):
    main = setup_cli(monkeypatch, tmp_path)
    prompts = []
    def username(prompt):
        prompts.append(prompt)
        return 'studio' if 'username' in prompt else ''
    def password(prompt):
        prompts.append(prompt)
        return PASSWORD
    monkeypatch.setattr('builtins.input', username)
    monkeypatch.setattr(getpass, 'getpass', password)
    main.main()
    assert prompts[0].endswith('username: ')
    assert prompts[1].startswith('Remote access password')
    assert prompts[2] == 'Confirm password: '
    assert 'port' in prompts[3] and '5000' in prompts[3]
    config = RemoteAccessConfig(main.CONFIG_DIR / 'auth.json')
    config.load()
    app = Flask(__name__)
    register(app, AccessPolicy('0.0.0.0', config))
    client = app.test_client()
    status = client.get('/api/remote-access').json
    assert status['enabled'] and status['username'] == 'studio'
    assert config.authenticate('studio', PASSWORD)
    output = capsys.readouterr()
    assert PASSWORD not in output.out + output.err
    assert 'restart' in output.out


def test_cli_retries_invalid_username_short_password_and_mismatch(tmp_path, monkeypatch):
    main = setup_cli(monkeypatch, tmp_path)
    usernames = iter(['bad:name', 'studio', ''])
    passwords = iter(['short', PASSWORD, 'mismatch', PASSWORD, PASSWORD])
    monkeypatch.setattr('builtins.input', lambda _: next(usernames))
    monkeypatch.setattr(getpass, 'getpass', lambda _: next(passwords))
    main.main()
    config = RemoteAccessConfig(main.CONFIG_DIR / 'auth.json')
    config.load()
    assert config.authenticate('studio', PASSWORD)


@pytest.mark.parametrize('failure', [EOFError, KeyboardInterrupt, getpass.GetPassWarning])
def test_cancelled_or_unsafe_prompt_does_not_change_credentials(tmp_path, monkeypatch, failure):
    main = setup_cli(monkeypatch, tmp_path)
    config = RemoteAccessConfig(main.CONFIG_DIR / 'auth.json')
    config.update(enabled=True, username='original', password=PASSWORD)
    original = config.path.read_bytes()
    monkeypatch.setattr('builtins.input', lambda _: 'changed')
    def fail(_):
        if failure is getpass.GetPassWarning:
            warnings.warn('Cannot control echo', getpass.GetPassWarning)
        raise failure
    monkeypatch.setattr(getpass, 'getpass', fail)
    with pytest.raises(SystemExit, match='settings were not changed'):
        main.main()
    assert config.path.read_bytes() == original


def test_disable_cli_preserves_credentials(tmp_path, monkeypatch):
    main = setup_cli(monkeypatch, tmp_path, '--disable-remote-access')
    config = RemoteAccessConfig(main.CONFIG_DIR / 'auth.json')
    config.update(enabled=True, username='studio', password=PASSWORD, port=8123)
    main.main()
    config.load()
    assert not config.enabled and config.configured
    assert not config.authenticate('studio', PASSWORD)
    assert config.port == 8123


@pytest.mark.parametrize('extra,expected', [([], '0.0.0.0'), (['--host', '127.0.0.1'], '127.0.0.1'),
                                          (['--demo'], '127.0.0.1'), (['--debug', 'profire2626'], '127.0.0.1')])
def test_startup_uses_saved_enabled_flag_and_explicit_host(tmp_path, monkeypatch, extra, expected):
    main = setup_cli(monkeypatch, tmp_path)
    config = RemoteAccessConfig(main.CONFIG_DIR / 'auth.json')
    config.update(enabled=True, username='studio', password=PASSWORD)
    monkeypatch.setattr(sys, 'argv', ['main.py', '--headless', *extra])
    import ffado_webmixer.access as access
    observed = []
    def policy(host, remote):
        observed.append(host)
        return AccessPolicy(host, remote)
    monkeypatch.setattr(access, 'AccessPolicy', policy)
    def stop(*_):
        raise RuntimeError('Stopped before hardware initialization')
    monkeypatch.setattr(main, 'create_backends', stop)
    with pytest.raises(RuntimeError, match='Stopped before hardware'):
        main.main()
    assert observed == [expected]


def test_remote_access_tab_is_accessible_and_uses_password_fields():
    from test_settings_qjackctl import SettingsHTML
    root = Path(__file__).resolve().parents[1] / 'src/ffado_webmixer/assets/static'
    parser = SettingsHTML()
    parser.feed((root / 'index.html').read_text())
    assert parser.ids['tab-remote-access'][1]['aria-controls'] == 'pane-remote-access'
    assert parser.ids['pane-remote-access'][1]['aria-labelledby'] == 'tab-remote-access'
    for name in ('remoteAccessPassword', 'remoteAccessConfirm'):
        assert parser.ids[name][1]['type'] == 'password'
        assert parser.ids[name][1]['autocomplete'] == 'new-password'
    port = parser.ids['remoteAccessPort'][1]
    assert port['type'] == 'number' and port['placeholder'] == '5000'
    assert port['min'] == '1' and port['max'] == '65535'
    assert port['data-gesture-edit'] == 'direct'


@pytest.mark.parametrize('port,expected', [('', 5000), ('   ', 5000), (1, 1),
                                          ('8123', 8123), (' 8123 ', 8123), (65535, 65535)])
def test_gui_port_is_validated_persisted_and_applied_after_restart(app, credentials, port, expected):
    password_hash = credentials._password_hash
    response = app.test_client().post('/api/remote-access', json={
        'enabled': True, 'username': 'studio', 'port': port})
    assert response.status_code == 200
    assert response.json['port'] == expected
    assert response.json['listening_port'] == 5000
    assert response.json['restart_required'] is (expected != 5000)
    assert app.ffado_port == 5000  # Saving cannot silently move a live listener.
    assert credentials._password_hash == password_hash
    reloaded = RemoteAccessConfig(credentials.path)
    reloaded.load()
    assert reloaded.port == expected
    restarted = Flask('restarted')
    register(restarted, AccessPolicy('0.0.0.0', reloaded))
    assert restarted.ffado_port == expected
    assert not restarted.test_client().get('/api/remote-access').json['restart_required']


@pytest.mark.parametrize('port', [None, True, False, 0, -1, 65536, 12.5, '12.5',
                                 '1e3', 'abc', [], {}, '１２３４'])
def test_invalid_gui_port_keeps_previous_file_and_credentials(app, credentials, port):
    original = credentials.path.read_bytes()
    response = app.test_client().post('/api/remote-access', json={
        'enabled': True, 'username': 'studio', 'port': port})
    assert response.status_code == 400
    assert credentials.port == 5000
    assert credentials.path.read_bytes() == original
    assert credentials.authenticate('studio', PASSWORD)


def test_blank_port_restores_default_and_omitted_port_preserves_custom_value(app, credentials):
    client = app.test_client()
    payload = {'enabled': True, 'username': 'studio'}
    assert client.post('/api/remote-access', json=dict(payload, port=8123)).json['port'] == 8123
    assert client.post('/api/remote-access', json=payload).json['port'] == 8123
    assert client.post('/api/remote-access', json=dict(payload, port='')).json['port'] == 5000


def test_existing_credentials_without_port_use_default(credentials):
    record = json.loads(credentials.path.read_text())
    del record['port']
    credentials.path.write_text(json.dumps(record))
    restored = RemoteAccessConfig(credentials.path)
    restored.load()
    assert restored.port == 5000
    assert restored.authenticate('studio', PASSWORD)


@pytest.mark.parametrize('port', [None, 0, -1, 65536, 'invalid', True])
def test_corrupt_saved_port_is_rejected(credentials, port):
    record = json.loads(credentials.path.read_text())
    record['port'] = port
    credentials.path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='Invalid remote-access configuration'):
        RemoteAccessConfig(credentials.path).load()


@pytest.mark.parametrize('answer,expected', [('', 5000), ('8123', 8123)])
def test_cli_optional_port_uses_the_same_configuration_as_gui(tmp_path, monkeypatch, answer, expected):
    main = setup_cli(monkeypatch, tmp_path)
    answers = iter(['studio', answer])
    monkeypatch.setattr('builtins.input', lambda _: next(answers))
    monkeypatch.setattr(getpass, 'getpass', lambda _: PASSWORD)
    main.main()
    config = RemoteAccessConfig(main.CONFIG_DIR / 'auth.json')
    config.load()
    assert config.port == expected
    assert json.loads(config.path.read_text())['port'] == expected
    assert config.authenticate('studio', PASSWORD)


def test_cli_retries_invalid_port_without_reprompting_for_password(tmp_path, monkeypatch):
    main = setup_cli(monkeypatch, tmp_path)
    answers = iter(['studio', '0', '65536', 'invalid', '8123'])
    passwords = iter([PASSWORD, PASSWORD])
    monkeypatch.setattr('builtins.input', lambda _: next(answers))
    monkeypatch.setattr(getpass, 'getpass', lambda _: next(passwords))
    main.main()
    config = RemoteAccessConfig(main.CONFIG_DIR / 'auth.json')
    config.load()
    assert config.port == 8123


def test_cancelled_port_prompt_does_not_save_credentials(tmp_path, monkeypatch):
    main = setup_cli(monkeypatch, tmp_path)
    config = RemoteAccessConfig(main.CONFIG_DIR / 'auth.json')
    config.update(enabled=True, username='original', password=PASSWORD, port=8123)
    original = config.path.read_bytes()
    def answer(prompt):
        if 'port' in prompt:
            raise EOFError
        return 'new-name'
    monkeypatch.setattr('builtins.input', answer)
    monkeypatch.setattr(getpass, 'getpass', lambda _: PASSWORD)
    with pytest.raises(SystemExit, match='settings were not changed'):
        main.main()
    assert config.path.read_bytes() == original


def test_about_and_browser_links_use_running_port_until_restart(credentials, monkeypatch):
    from ffado_webmixer import server
    from ffado_webmixer.config import Config
    from ffado_webmixer.demo import DemoMixer
    import webbrowser
    credentials.update(enabled=True, username='studio', port=8123)
    backend = DemoMixer()
    app = server.create_app(backend, backend.describe(), Config(None),
                            access_policy=AccessPolicy('0.0.0.0', credentials))
    monkeypatch.setattr(server, 'lan_ip', lambda: '192.0.2.10')
    opened = []
    monkeypatch.setattr(webbrowser, 'open', lambda url: opened.append(url) or True)
    client = app.test_client()
    assert client.get('/api/about').json['address'] == 'http://192.0.2.10:8123'
    assert client.post('/api/open-mixer', json={}).status_code == 200
    assert opened == ['http://192.0.2.10:8123/']
    assert client.post('/api/remote-access', json={
        'enabled': True, 'username': 'studio', 'port': 9000}).json['restart_required']
    assert client.get('/api/about').json['address'] == 'http://192.0.2.10:8123'
