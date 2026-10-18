import queue
import threading

class Hub:
    """Passes each change on to every open page (desktop window, phone, other browsers)."""

    def __init__(self):
        self._clients = {}
        self._lock = threading.Lock()

    def subscribe(self, device=None):
        client = queue.Queue(maxsize=500)

        with self._lock:
            self._clients[client] = device

        return client

    def unsubscribe(self, client):
        with self._lock:
            self._clients.pop(client, None)

    def publish(self, event, origin):
        # The sender's id lets that page ignore its own change coming back.
        event["origin"] = origin

        with self._lock:
            targets = [client for client, device in self._clients.items()
                       if device is None or event.get('device') is None
                       or device == event.get('device')]

        for client in targets:
            try:
                client.put_nowait(event)
            except queue.Full:
                # A stuck page just misses events and resyncs when it reconnects.
                pass
