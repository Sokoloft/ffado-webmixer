"""Loss recovery and lifecycle tests for the mixer change stream."""
import importlib.util
import json
import sys
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from ffado_webmixer.services.events import Hub


class EventHubTest(unittest.TestCase):
    def test_overflow_requests_snapshot_without_blocking_other_clients(self):
        hub = Hub(queue_size=2)
        slow = hub.subscribe('device-a')
        fast = hub.subscribe('device-a')
        other = hub.subscribe('device-b')
        original = {'type': 'strip', 'device': 'device-a'}
        for number in range(3):
            hub.publish(dict(original, value=number), 'browser')
            self.assertEqual(fast.get_nowait()['value'], number)
        self.assertEqual(original, {'type': 'strip', 'device': 'device-a'})
        self.assertEqual(slow.get_nowait(), {
            'type': 'resync', 'reason': 'overflow', 'device': 'device-a'})
        self.assertTrue(slow.empty())
        self.assertTrue(other.empty())
        hub.publish(dict(original, value=3), 'browser')
        self.assertEqual(slow.get_nowait()['value'], 3)

    def test_publish_does_not_change_the_callers_event(self):
        hub = Hub()
        client = hub.subscribe()
        event = {'type': 'layout'}
        hub.publish(event, 'browser')
        self.assertEqual(event, {'type': 'layout'})
        self.assertEqual(client.get_nowait()['origin'], 'browser')

    def test_concurrent_publishers_preserve_an_overflow_barrier(self):
        hub = Hub(queue_size=2)
        client = hub.subscribe()

        def publish(origin):
            for number in range(100):
                hub.publish({'type': 'strip', 'value': number}, origin)

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(publish, ['a', 'b', 'c', 'd']))
        self.assertEqual(client.get_nowait()['type'], 'resync')
        self.assertEqual(client.get_nowait()['type'], 'strip')
        self.assertTrue(client.empty())

    def test_unsubscribed_clients_stop_receiving_events(self):
        hub = Hub()
        client = hub.subscribe()
        hub.unsubscribe(client)
        hub.publish({'type': 'layout'}, 'browser')
        self.assertTrue(client.empty())


class StreamingResponse:
    """Minimal response supporting iteration and explicit close callbacks."""
    def __init__(self, response, **options):
        self.response = response
        self.options = options
        self.callbacks = []

    def call_on_close(self, callback):
        self.callbacks.append(callback)

    def close(self):
        self.response.close()
        for callback in self.callbacks:
            callback()


class EventRouteTest(unittest.TestCase):
    def setUp(self):
        self.request = types.SimpleNamespace(args={}, environ={})
        flask = types.ModuleType('flask')
        flask.request = self.request
        flask.jsonify = lambda **kwargs: kwargs
        flask.Response = StreamingResponse
        path = Path(__file__).parents[1] / 'src/ffado_webmixer/api/events.py'
        spec = importlib.util.spec_from_file_location('ffado_webmixer.api._event_sync_test_api', path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'flask': flask}):
            spec.loader.exec_module(module)
        routes = {}

        def register(path):
            def decorate(handler):
                routes[path] = handler
                return handler
            return decorate

        self.hub = Hub(queue_size=2)
        self.manager = types.SimpleNamespace(current_guid='device-a')
        module.register(types.SimpleNamespace(get=register), self.hub, self.manager)
        self.events = routes['/api/events']

    def test_overflow_is_visible_on_the_open_stream(self):
        response = self.events()
        self.assertEqual(next(response.response), 'retry: 1000\n\n')
        for _ in range(3):
            self.hub.publish({'type': 'layout', 'device': 'device-a'}, 'browser')
        event = json.loads(next(response.response).removeprefix('data: '))
        self.assertEqual(event['type'], 'resync')
        self.assertEqual(event['reason'], 'overflow')
        self.assertEqual(response.options['headers']['Cache-Control'], 'no-store')
        response.close()
        self.assertFalse(self.hub._clients)

    def test_response_closed_before_first_iteration_removes_subscription(self):
        response = self.events()
        self.assertEqual(len(self.hub._clients), 1)
        response.close()
        self.assertFalse(self.hub._clients)

    def test_stream_keeps_the_device_resolved_before_iteration(self):
        response = self.events()
        self.manager.current_guid = 'device-b'
        next(response.response)
        self.hub.publish({'type': 'layout', 'device': 'device-b'}, 'browser')
        self.hub.publish({'type': 'layout', 'device': 'device-a'}, 'browser')
        event = json.loads(next(response.response).removeprefix('data: '))
        self.assertEqual(event['device'], 'device-a')
        response.close()

    def test_stale_device_reconnect_is_rejected_before_subscribing(self):
        self.request.args['device'] = 'device-b'
        body, status = self.events()
        self.assertEqual(status, 409)
        self.assertIn('reload', body['error'])
        self.assertFalse(self.hub._clients)


if __name__ == '__main__':
    unittest.main()
