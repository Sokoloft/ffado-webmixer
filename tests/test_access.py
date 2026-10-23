"""Exercise authentication and browser-write checks with actual Flask requests."""
from base64 import b64encode

import pytest
from flask import Flask, Response

from ffado_webmixer.access import AccessPolicy, register
from ffado_webmixer.remote_access import RemoteAccessConfig


PASSWORD = 'test-password-with-32-characters!!'
REMOTE = {'REMOTE_ADDR': '192.168.1.20'}


def authorization(password=PASSWORD, username='studio'):
    value = b64encode(f'{username}:{password}'.encode()).decode()
    return {'Authorization': f'Basic {value}'}


@pytest.fixture
def mixer():
    app = Flask(__name__)
    credentials = RemoteAccessConfig()
    credentials.update(enabled=True, username='studio', password=PASSWORD)
    register(app, AccessPolicy('0.0.0.0', credentials))
    writes = []

    @app.get('/')
    def index():
        return 'mixer'

    @app.post('/api/set')
    def change():
        writes.append(True)
        return {'ok': True}

    @app.get('/api/events')
    def events():
        return Response(iter(['data: {}\n\n']), mimetype='text/event-stream')

    return app.test_client(), writes


@pytest.mark.parametrize('path', ['/', '/api/events', '/static/index.js'])
def test_remote_requests_require_password_including_streams_and_assets(mixer, path):
    client, writes = mixer
    response = client.get(path, environ_overrides=REMOTE)
    assert response.status_code == 401
    assert response.headers['WWW-Authenticate'].startswith('Basic realm=')
    assert writes == []


@pytest.mark.parametrize('headers', [
    {}, authorization('wrong'), authorization(username='other'),
    {'Authorization': 'Bearer ' + PASSWORD}, {'Authorization': 'Basic malformed'},
    {'X-Forwarded-For': '127.0.0.1', 'X-Forwarded-Host': 'localhost'},
])
def test_unauthenticated_remote_writes_never_reach_hardware(mixer, headers):
    client, writes = mixer
    response = client.post('/api/set', json={}, headers=headers, environ_overrides=REMOTE)
    assert response.status_code == 401
    assert writes == []


def test_authenticated_remote_reads_writes_and_streams(mixer):
    client, writes = mixer
    assert client.get('/', headers=authorization(), environ_overrides=REMOTE).status_code == 200
    assert client.post('/api/set', json={}, headers=authorization(),
                       environ_overrides=REMOTE).json == {'ok': True}
    response = client.get('/api/events', headers=authorization(), environ_overrides=REMOTE)
    assert response.status_code == 200
    assert response.data == b'data: {}\n\n'
    assert writes == [True]


def test_local_desktop_needs_no_password_and_has_response_headers(mixer):
    client, writes = mixer
    response = client.post('/api/set', json={})
    assert response.status_code == 200 and writes == [True]
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'


@pytest.mark.parametrize('base_url', ['http://localhost:5000', 'http://127.0.0.1:5000'])
def test_same_origin_browser_writes_are_accepted(mixer, base_url):
    client, writes = mixer
    response = client.post('/api/set', json={}, base_url=base_url,
                           headers={'Origin': base_url, 'Sec-Fetch-Site': 'same-origin'})
    assert response.status_code == 200 and writes == [True]


@pytest.mark.parametrize('headers', [
    {'Origin': 'https://unrelated.example'}, {'Origin': 'null'},
    {'Origin': 'http://localhost:9999'}, {'Sec-Fetch-Site': 'cross-site'},
])
@pytest.mark.parametrize('remote', [False, True])
def test_cross_origin_writes_are_blocked_even_with_credentials(mixer, headers, remote):
    client, writes = mixer
    response = client.post('/api/set', json={}, headers={**authorization(), **headers},
                           environ_overrides=REMOTE if remote else {})
    assert response.status_code == 403
    assert writes == []


@pytest.mark.parametrize('content_type', ['text/plain', 'application/x-www-form-urlencoded'])
def test_simple_form_writes_are_rejected(mixer, content_type):
    client, writes = mixer
    response = client.post('/api/set', data='{}', content_type=content_type)
    assert response.status_code == 415
    assert writes == []


def test_loopback_connection_with_hostile_host_cannot_bypass_authentication(mixer):
    client, writes = mixer
    response = client.post('/api/set', json={}, base_url='http://rebound.example:5000')
    assert response.status_code == 401
    assert writes == []


def test_default_listener_is_local_only_and_does_not_authenticate_remote_users():
    policy = AccessPolicy()
    assert policy.host == '127.0.0.1'
    assert policy.permits_local('::ffff:127.0.0.1', 'localhost')
    assert not policy.permits_local('192.168.1.2', 'localhost')
    assert not policy.permits_local(None, 'localhost')
    app = Flask(__name__)
    register(app, policy)
    response = app.test_client().get('/', headers=authorization(), environ_overrides=REMOTE)
    assert response.status_code == 401


@pytest.mark.parametrize('credentials', [None, RemoteAccessConfig()])
def test_lan_binding_requires_saved_enabled_credentials_before_server_or_hardware_start(credentials):
    with pytest.raises(ValueError, match='--enable-remote-access'):
        AccessPolicy('0.0.0.0', credentials)


def test_password_is_not_in_policy_representation():
    credentials = RemoteAccessConfig()
    credentials.update(enabled=True, username='studio', password=PASSWORD)
    assert PASSWORD not in repr(AccessPolicy('0.0.0.0', credentials))


def test_cli_rejects_lan_without_saved_password_even_with_old_environment_variable(tmp_path, monkeypatch):
    import sys
    from ffado_webmixer import main
    monkeypatch.setenv('FFADO_WEBMIXER_TOKEN', PASSWORD)
    monkeypatch.setattr(main, 'CONFIG_DIR', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['ffado-webmixer', '--demo', '--headless', '--host', '0.0.0.0'])
    monkeypatch.setattr(main, 'create_backends', lambda *_: pytest.fail('Must not initialize hardware'))
    with pytest.raises(SystemExit, match='--enable-remote-access'):
        main.main()
