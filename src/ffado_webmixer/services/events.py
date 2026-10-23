import queue
import threading

class Hub:
    """Passes each change on to every open page (desktop window, phone, other browsers)."""

    def __init__(self, queue_size=500):
        if queue_size < 1:
            raise ValueError('Event queues must have a positive capacity')
        self._queue_size = queue_size
        self._clients = {}
        self._lock = threading.Lock()

    def subscribe(self, device=None):
        client = queue.Queue(maxsize=self._queue_size)

        with self._lock:
            self._clients[client] = device

        return client

    def unsubscribe(self, client):
        with self._lock:
            self._clients.pop(client, None)

    def publish(self, event, origin):
        # The sender's id lets that page ignore its own change coming back.
        event = dict(event, origin=origin)

        with self._lock:
            # Keep publishers ordered, including the overflow marker. Otherwise
            # another publisher can fill a drained queue before its marker lands.
            for client, device in self._clients.items():
                if device is not None and event.get('device') not in (None, device):
                    continue
                try:
                    client.put_nowait(event)
                except queue.Full:
                    # Queued deltas no longer describe a complete history.
                    # Replace them with an explicit request for current state;
                    # the connection can recover without waiting for a disconnect.
                    while True:
                        try:
                            client.get_nowait()
                        except queue.Empty:
                            break
                    client.put_nowait({'type': 'resync', 'reason': 'overflow',
                                       'device': device})
