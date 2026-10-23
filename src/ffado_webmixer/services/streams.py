"""Subscription cleanup and wakeup for revocable server-sent event streams."""
import queue
import threading


class StreamClosed(Exception):
    pass


class StreamSubscription:
    def __init__(self, client, unsubscribe, authorization=None):
        self.client = client
        self.unsubscribe = unsubscribe
        self.authorization = authorization
        self.closed = threading.Event()
        if authorization is not None:
            config, revision = authorization
            config.watch_stream(revision, self.close)

    def close(self):
        # Unsubscribe is idempotent; generator-finally, response-close and
        # credential revocation may all reach this method concurrently.
        self.closed.set()
        self.unsubscribe()
        if self.authorization is not None:
            config, _ = self.authorization
            config.unwatch_stream(self.close)
        # Wake a blocked reader. A full queue already has something to wake it;
        # get() checks closure before handing any queued payload to the stream.
        try:
            self.client.put_nowait(None)
        except queue.Full:
            pass

    def get(self, timeout):
        if self.closed.is_set():
            raise StreamClosed
        try:
            item = self.client.get(timeout=timeout)
        except queue.Empty:
            if self.closed.is_set():
                raise StreamClosed from None
            raise
        if self.closed.is_set():
            raise StreamClosed
        return item
