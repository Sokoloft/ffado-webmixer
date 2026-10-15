from flask import request
from ..services.stereo import change_stereo

def register(app, backend, description, config, broadcast):
    @app.post("/api/stereo")
    def set_stereo():
        return change_stereo(request.get_json(force=True), request.args.get("mix", 0, type=int), backend, description, config, broadcast)
