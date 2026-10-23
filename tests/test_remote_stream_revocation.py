"""Credential changes revoke active and not-yet-started remote SSE responses."""
import json
import queue
import threading
from types import SimpleNamespace

import pytest

from ffado_webmixer import server
from ffado_webmixer.access import AccessPolicy
from ffado_webmixer.api import mixer as mixer_routes
from ffado_webmixer.config import Config
from ffado_webmixer.remote_access import RemoteAccessConfig
from ffado_webmixer.services.events import Hub
from ffado_webmixer.services.peak_stream import PeakStreamHub
from test_access import PASSWORD, REMOTE, authorization
from test_peak_stream import DummyPeakDevice


PATHS = ['/api/events', '/api/peak-stream']


@pytest.fixture
def streams(tmp_path, monkeypatch):
    credentials = RemoteAccessConfig(tmp_path / 'auth.json')
    credentials.update(enabled=True, username='studio', password=PASSWORD)
    events, peaks = Hub(queue_size=2), PeakStreamHub(interval=.01)
    monkeypatch.setattr(server, 'Hub', lambda: events)
    monkeypatch.setattr(mixer_routes, 'PeakStreamHub', lambda: peaks)
    backend = DummyPeakDevice('1111111111111111')
    app = server.create_app(backend, {}, Config(None),
                            access_policy=AccessPolicy('0.0.0.0', credentials))
    app.testing = True
    responses = []

    def open_stream(path, *, remote=True, start=True, headers=None):
        with app.test_request_context(path, headers=headers or authorization(),
                                      environ_overrides=REMOTE if remote else {'REMOTE_ADDR': '127.0.0.1'}):
            response = app.full_dispatch_request()
        responses.append(response)
        assert response.status_code == 200
        if start:
            assert next(response.response).endswith('\n\n')
        return response

    def client_count(path):
        if path == '/api/events':
            return len(events._clients)
        return len(peaks._samplers[backend.guid].clients)

    yield SimpleNamespace(app=app, credentials=credentials, events=events, peaks=peaks,
                          backend=backend, open=open_stream, count=client_count)
    threads = [sampler.thread for sampler in peaks._samplers.values() if sampler.thread]
    for response in responses:
        response.close()
    for thread in threads:
        thread.join(timeout=1)
        assert not thread.is_alive()
    assert not credentials._stream_revocations


@pytest.mark.parametrize('path', PATHS)
@pytest.mark.parametrize('change', [
    {'enabled': False, 'username': 'studio'},
    {'enabled': True, 'username': 'new-name'},
    {'enabled': True, 'username': 'studio', 'password': 'a different long password'},
])
def test_changes_close_remote_streams_but_keep_local_streams(streams, path, change):
    remote = streams.open(path)
    local = streams.open(path, remote=False)
    # Leave queued data behind to verify revocation does not flush it to a client.
    for value in range(3):
        streams.events.publish({'type': 'strip', 'value': value}, 'test')
    response = streams.app.test_client().post('/api/remote-access', json=change)
    assert response.status_code == 200
    assert streams.count(path) == 1
    assert not streams.credentials._stream_revocations
    with pytest.raises(StopIteration):
        next(remote.response)
    assert next(local.response).startswith('data: ')
    assert streams.app.test_client().get(path, headers=authorization(),
                                        environ_overrides=REMOTE).status_code == 401


@pytest.mark.parametrize('path', PATHS)
@pytest.mark.parametrize('start', [False, True])
def test_revocation_unsubscribes_immediately_and_cannot_be_undone_by_reenabling(streams, path, start):
    response = streams.open(path, start=start)
    sampler = streams.peaks._samplers.get(streams.backend.guid)
    thread = sampler.thread if sampler else None
    streams.credentials.update(enabled=False, username='studio')
    assert streams.count(path) == 0
    if thread:
        thread.join(timeout=1)
        assert not thread.is_alive()
    streams.credentials.update(enabled=True, username='studio')
    with pytest.raises(StopIteration):
        next(response.response)
    new_response = streams.open(path)
    streams.events.publish({'type': 'layout'}, 'test')
    assert next(new_response.response).startswith('data: ')


@pytest.mark.parametrize('path', PATHS)
def test_credentials_changing_between_authentication_and_subscription_fail_closed(streams, path, monkeypatch):
    hub = streams.events if path == '/api/events' else streams.peaks
    subscribe = hub.subscribe

    def subscribe_after_change(*args):
        result = subscribe(*args)
        streams.credentials.update(enabled=False, username='studio')
        streams.credentials.update(enabled=True, username='studio')
        return result

    monkeypatch.setattr(hub, 'subscribe', subscribe_after_change)
    response = streams.open(path, start=False)
    assert streams.count(path) == 0
    with pytest.raises(StopIteration):
        next(response.response)
    assert not streams.credentials._stream_revocations


@pytest.mark.parametrize('path', PATHS)
@pytest.mark.parametrize('save_result', ['unchanged', 'invalid', 'failed'])
def test_unsuccessful_or_unchanged_settings_do_not_revoke(streams, path, save_result, monkeypatch):
    response = streams.open(path)
    payload = {'enabled': True, 'username': 'studio'}
    expected = 200
    if save_result == 'invalid':
        payload['password'] = 'short'
        expected = 400
    elif save_result == 'failed':
        payload['enabled'] = False
        def fail_save(record):
            raise OSError('simulated disk full')
        monkeypatch.setattr(streams.credentials, '_save', fail_save)
        expected = 500
    assert streams.app.test_client().post('/api/remote-access', json=payload).status_code == expected
    assert streams.count(path) == 1
    assert len(streams.credentials._stream_revocations) == 1
    streams.events.publish({'type': 'layout'}, 'test')
    assert next(response.response).startswith('data: ')
    response.close()
    response.close()
    assert not streams.credentials._stream_revocations


@pytest.mark.parametrize('path', PATHS)
def test_revocation_wakes_an_idle_reader(streams, path, monkeypatch):
    response = streams.open(path)
    entered, release = threading.Event(), threading.Event()
    if path == '/api/events':
        client = next(iter(streams.events._clients))
    else:
        # Hold the next simulated hardware read so the queue becomes idle.
        snapshot = streams.backend.peak_snapshot
        def blocked_snapshot():
            entered.set()
            assert release.wait(3)
            return snapshot()
        monkeypatch.setattr(streams.backend, 'peak_snapshot', blocked_snapshot)
        sampler = streams.peaks._samplers[streams.backend.guid]
        client = next(iter(sampler.clients))
        assert entered.wait(1)
        entered.clear()
        while True:
            try:
                client.get_nowait()
            except queue.Empty:
                break
    get = client.get
    def waiting_get(*args, **kwargs):
        entered.set()
        return get(*args, **kwargs)
    monkeypatch.setattr(client, 'get', waiting_get)
    result = []
    def read():
        result.append(next(response.response, 'closed'))
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        assert entered.wait(1)
        streams.credentials.update(enabled=False, username='studio')
        reader.join(timeout=1)
        assert not reader.is_alive()
        assert result == ['closed']
        assert streams.count(path) == 0
    finally:
        release.set()
        reader.join(timeout=1)


def test_reloading_changed_credentials_revokes_existing_streams(streams):
    response = streams.open('/api/events')
    record = json.loads(streams.credentials.path.read_text())
    record['enabled'] = False
    streams.credentials.path.write_text(json.dumps(record))
    streams.credentials.load()
    assert streams.count('/api/events') == 0
    with pytest.raises(StopIteration):
        next(response.response)


def test_rotation_revokes_both_stream_types_and_allows_new_credentials(streams):
    responses = [streams.open(path) for path in PATHS]
    assert len(streams.credentials._stream_revocations) == 2
    password = 'the newly configured password'
    response = streams.app.test_client().post('/api/remote-access', json={
        'enabled': True, 'username': 'new-name', 'password': password})
    assert response.status_code == 200
    for path, response in zip(PATHS, responses):
        assert streams.count(path) == 0
        with pytest.raises(StopIteration):
            next(response.response)
    for path in PATHS:
        response = streams.open(path, headers=authorization(password, 'new-name'))
        streams.events.publish({'type': 'layout'}, 'test')
        assert next(response.response).startswith('data: ')


@pytest.mark.parametrize('path', PATHS)
def test_early_response_close_removes_revocation_registration(streams, path):
    response = streams.open(path, start=False)
    assert len(streams.credentials._stream_revocations) == 1
    response.close()
    response.close()
    assert not streams.credentials._stream_revocations
    assert streams.count(path) == 0
