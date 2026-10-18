import json
import queue
from flask import Response

def register(app, hub, device_manager=None):
    @app.get("/api/events")
    def events():
        """Server-sent events: one long-lived response per open page."""
        # Resolve the selected GUID before streaming; the session proxy must
        # never be accessed from the SSE generator after its request context
        # has finished. Only forward events for this device.
        selected = device_manager.current_guid if device_manager else None
        client = hub.subscribe(selected)

        def stream():
            try:
                yield "retry: 1000\n\n"

                while True:
                    try:
                        event = client.get(timeout=15)
                    except queue.Empty:
                        # Also lets the server notice pages that have closed.
                        yield ": keepalive\n\n"
                        continue

                    yield f"data: {json.dumps(event)}\n\n"
            finally:
                hub.unsubscribe(client)

        return Response(
            stream(),
            mimetype="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )
