"""Live meter stream regression: cadence, fanout, stale frames, device safety."""
import json
import importlib.util
import queue
import threading
import time
import unittest
from ffado_webmixer.services.peak_stream import PeakStreamHub, SAMPLE_INTERVAL


class DummyPeakDevice:
    def __init__(self, guid, delay=0):
        self.guid = guid
        self.calls = 0
        self.delay = delay
        self.lock = threading.Lock()

    def peak_snapshot(self):
        if self.delay:
            time.sleep(self.delay)
        with self.lock:
            self.calls += 1
            count = self.calls
        return {'guid': self.guid, 'available': True,
                'channels': {'0': {'destination': 'Mixer/In:01',
                                   'level': count / 1000, 'db': -20,
                                   'near_full_scale': False}},
                'destination_levels': {}}


class PeakStreamTest(unittest.TestCase):
    def test_default_cadence_matches_reference_project(self):
        self.assertAlmostEqual(SAMPLE_INTERVAL, .1)

    def test_two_viewers_share_one_hw_read_per_sample_and_idle_stops(self):
        dev = DummyPeakDevice('1111111111111111')
        hub = PeakStreamHub(interval=.045)
        sampler1, first = hub.subscribe(dev)
        sampler2, second = hub.subscribe(dev)
        self.assertIs(sampler1, sampler2)
        a = json.loads(first.get(timeout=1))
        b = json.loads(second.get(timeout=1))
        self.assertEqual(a, b)  # both clients received the SAME sample
        self.assertEqual(a['guid'], dev.guid)
        self.assertEqual(dev.calls, 1)
        time.sleep(.16)
        # Both queues are bounded; a frozen browser cannot cause latency or
        # unbounded server memory growth, and drops intermediate samples.
        self.assertEqual(first.maxsize, 1)
        self.assertEqual(second.maxsize, 1)
        last = json.loads(first.get_nowait())
        self.assertGreater(last['channels']['0']['level'], a['channels']['0']['level'])
        self.assertLessEqual(dev.calls, 6)  # not once per subscriber
        hub.unsubscribe(sampler1, first)
        hub.unsubscribe(sampler2, second)
        sampler1.thread.join(timeout=1)
        self.assertFalse(sampler1.thread and sampler1.thread.is_alive())
        frozen = dev.calls
        time.sleep(.1)
        self.assertEqual(dev.calls, frozen)
        # A fresh subscriber restarts the one sampler for this GUID.
        sampler3, client3 = hub.subscribe(dev)
        self.assertIs(sampler3, sampler1)
        self.assertEqual(json.loads(client3.get(timeout=1))['guid'], dev.guid)
        hub.unsubscribe(sampler3, client3)

    def test_concurrent_devices_have_disjoint_payloads(self):
        hub = PeakStreamHub(interval=.1)
        first = DummyPeakDevice('1111111111111111')
        second = DummyPeakDevice('2222222222222222')
        a, sub_a = hub.subscribe(first)
        b, sub_b = hub.subscribe(second)
        self.assertNotEqual(a, b)
        self.assertEqual(json.loads(sub_a.get(timeout=1))['guid'], first.guid)
        self.assertEqual(json.loads(sub_b.get(timeout=1))['guid'], second.guid)
        hub.unsubscribe(a, sub_a)
        hub.unsubscribe(b, sub_b)

    def test_slow_hardware_cannot_build_backlog(self):
        dev = DummyPeakDevice('1111111111111111', delay=.08)
        hub = PeakStreamHub(interval=.03)
        sampler, client = hub.subscribe(dev)
        time.sleep(.34)
        item = json.loads(client.get(timeout=1))
        self.assertGreaterEqual(item['channels']['0']['level'], .002)
        self.assertEqual(client.qsize(), 0)
        hub.unsubscribe(sampler, client)
        sampler.thread.join(timeout=1)

    def test_transient_failure_yields_unavailable_then_recovers(self):
        dev = DummyPeakDevice('1111111111111111')
        normal = dev.peak_snapshot
        def intermittent():
            if not getattr(dev, 'failed', False):
                dev.failed = True
                raise RuntimeError('temporary D-Bus timeout')
            return normal()
        dev.peak_snapshot = intermittent
        hub = PeakStreamHub(interval=.02)
        sampler, client = hub.subscribe(dev)
        self.assertFalse(json.loads(client.get(timeout=1))['available'])
        self.assertTrue(json.loads(client.get(timeout=2))['available'])
        hub.unsubscribe(sampler, client)

    @unittest.skipUnless(importlib.util.find_spec("flask"), "Flask is not installed in the offline test environment")
    def test_flask_route_uses_selected_device_and_sse(self):
        from ffado_webmixer.api.mixer import register
        from flask import Flask
        app = Flask('peak_stream_test')
        backend = DummyPeakDevice('1111111111111111')
        # Only /api/peaks and /api/peak-stream are called during this test.
        register(app, backend, {}, None, lambda e: None)
        with app.test_client() as client:
            response = client.get('/api/peak-stream', buffered=False)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.mimetype == 'text/event-stream')
            self.assertEqual(next(response.response), b': connected\n\n')
            event = next(response.response)
            self.assertTrue(event.startswith(b'data: '))
            self.assertEqual(json.loads(event.removeprefix(b'data: ').strip())['guid'],backend.guid)
            response.close()


if __name__ == '__main__':
    unittest.main()
