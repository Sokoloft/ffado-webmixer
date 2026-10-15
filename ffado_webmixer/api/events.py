import json
import queue
from flask import Response

def register(app, hub):
    @app.get("/api/events")
    def events():
        """Server-sent events: one long-lived response per open page."""
        client = hub.subscribe()

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
