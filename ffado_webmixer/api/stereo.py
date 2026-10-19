"""HTTP boundary for validated stereo pair changes."""
import re
from flask import jsonify, request
from ..services.stereo import change_stereo


def register(app, backend, description, config, broadcast):
    @app.post('/api/stereo')
    def set_stereo():
        raw_mix = request.args.get('mix', '0')
        # Flask's type=int fallback silently turns mix=garbage into Bus 1.
        # Do not accidentally change another bus when the URL is malformed.
        if not isinstance(raw_mix, str) or not re.fullmatch(r'[0-9]{1,8}', raw_mix):
            return jsonify(error='Invalid output bus'), 400
        mix = int(raw_mix)
        return change_stereo(request.get_json(force=True), mix,
                             backend, backend.describe(), config, broadcast)
