import json
import queue
from flask import Response, jsonify, request
from ..services.streams import StreamClosed, StreamSubscription

def register(app, hub, device_manager=None):
    @app.get("/api/events")
    def events():
        """Server-sent events: one long-lived response per open page."""
        # Resolve the selected GUID before streaming; the session proxy must
        # never be accessed from the SSE generator after its request context
        # has finished. Only forward events for this device.
        selected = device_manager.current_guid if device_manager else None
        # EventSource cannot set the device header used by other API requests.
        # Reject an old tab reconnecting after a shared session changes devices.
        expected = request.args.get('device')
        if expected and expected != selected:
            return jsonify(error='Selected mixer changed in another tab; reload this page'), 409
        client = hub.subscribe(selected)
        subscription = StreamSubscription(client, lambda: hub.unsubscribe(client),
                                          request.environ.get('ffado_webmixer.remote_authorization'))

        def stream():
            try:
                if subscription.closed.is_set():
                    return
                yield "retry: 1000\n\n"

                while True:
                    try:
                        event = subscription.get(timeout=15)
                    except StreamClosed:
                        return
                    except queue.Empty:
                        # Also lets the server notice pages that have closed.
                        yield ": keepalive\n\n"
                        continue

                    yield f"data: {json.dumps(event)}\n\n"
            finally:
                subscription.close()

        response = Response(
            stream(),
            mimetype="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
        )
        # Closing a response before iteration also needs to remove its client.
        response.call_on_close(subscription.close)
        return response
