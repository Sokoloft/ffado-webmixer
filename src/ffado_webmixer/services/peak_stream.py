"""Shared, demand-driven live FFADO peak sampler.

Inspired by ffado-web-mixer's one-reader/many-client push architecture, but
uses Flask's built-in Server-Sent Events rather than adding aiohttp/websockets.
Each physical device is sampled at most once per tick, regardless of browsers.
Only the latest frame is queued for slow subscribers (old peaks are discarded).
"""
import json
import queue
import threading
import time

SAMPLE_INTERVAL = 0.1  # FFADO reference project's 100 ms sampling cadence


class _Sampler:
    def __init__(self, backend, interval):
        self.backend = backend
        self.interval = interval
        self.clients = set()
        self.lock = threading.Lock()
        self.thread = None

    def subscribe(self):
        client = queue.Queue(maxsize=1)
        with self.lock:
            self.clients.add(client)
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._run, daemon=True,
                                               name=f'ffado-peaks-{self.backend.guid[-6:]}')
                self.thread.start()
        return client

    def unsubscribe(self, client):
        with self.lock:
            self.clients.discard(client)

    def _run(self):
        # A disconnecting browser need not keep FFADO polling. An empty set
        # ends this thread and releases the device's sampler slot.
        while True:
            started = time.monotonic()
            with self.lock:
                if not self.clients:
                    self.thread = None
                    return
                clients = tuple(self.clients)
            failed = False
            try:
                frame = self.backend.peak_snapshot()
            except Exception as exc:
                failed = True
                # Keep the stream alive through transient FFADO/D-Bus errors;
                # the browser should hide invalid meters, never use stale data.
                frame = {'available': False, 'guid': self.backend.guid,
                         'channels': {}, 'destination_levels': {},
                         'error': str(exc)}
            # Encode once; don't do any work proportional to subscriber count
            # on the hardware thread except a nonblocking latest-frame send.
            payload = json.dumps(frame, separators=(',', ':'))
            for client in clients:
                try:
                    client.put_nowait(payload)
                except queue.Full:
                    try:
                        client.get_nowait()
                        client.put_nowait(payload)
                    except queue.Empty:
                        pass
                    except queue.Full:
                        pass
            delay = self.interval - (time.monotonic() - started)
            # Don't hammer a disconnected FFADO service on every tenth of a
            # second. Once the service recovers normal 100 ms cadence resumes.
            if failed:
                delay = max(delay, 0.5)
            if delay > 0:
                time.sleep(delay)


class PeakStreamHub:
    def __init__(self, interval=SAMPLE_INTERVAL):
        self.interval = interval
        self._lock = threading.RLock()
        self._samplers = {}

    def subscribe(self, backend):
        with self._lock:
            sampler = self._samplers.get(backend.guid)
            if sampler is None:
                sampler = _Sampler(backend, self.interval)
                self._samplers[backend.guid] = sampler
            return sampler, sampler.subscribe()

    @staticmethod
    def unsubscribe(sampler, client):
        sampler.unsubscribe(client)
