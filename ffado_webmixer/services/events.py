import queue
import threading

class Hub:
    """Passes each change on to every open page (desktop window, phone, other browsers)."""

    def __init__(self):
        self._clients = set()
        self._lock = threading.Lock()

    def subscribe(self):
        client = queue.Queue(maxsize=500)

        with self._lock:
            self._clients.add(client)

        return client

    def unsubscribe(self, client):
        with self._lock:
            self._clients.discard(client)

    def publish(self, event, origin):
        # The sender's id lets that page ignore its own change coming back.
        event["origin"] = origin

        with self._lock:
            targets = list(self._clients)

        for client in targets:
            try:
                client.put_nowait(event)
            except queue.Full:
                # A stuck page just misses events and resyncs when it reconnects.
                pass
