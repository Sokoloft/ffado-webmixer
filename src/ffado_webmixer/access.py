"""Listener policy and browser request checks for local and LAN control."""
from dataclasses import dataclass, field
from ipaddress import ip_address
from secrets import compare_digest
from urllib.parse import urlsplit


def bind_address(value):
    """Accept explicit IP addresses, with localhost as a loopback shorthand."""
    if value == 'localhost':
        return '127.0.0.1'
    try:
        return str(ip_address(value))
    except ValueError as exc:
        raise ValueError('--host must be an IP address or localhost') from exc


def _loopback(value):
    try:
        address = ip_address(value)
        if address.version == 6 and address.ipv4_mapped:
            address = address.ipv4_mapped
        return address.is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class AccessPolicy:
    host: str = '127.0.0.1'
    token: str | None = field(default=None, repr=False)

    def __post_init__(self):
        object.__setattr__(self, 'host', bind_address(self.host))
        if not _loopback(self.host) and (not self.token or len(self.token.strip()) < 16):
            raise ValueError('LAN access requires FFADO_WEBMIXER_TOKEN with at least 16 characters')

    def permits_local(self, remote_address, hostname):
        # Requiring a loopback Host as well prevents DNS rebinding from turning
        # a hostile website into a password-free local client. Forwarded headers
        # are deliberately not trusted to grant this exception.
        return _loopback(remote_address or '') and (
            hostname == 'localhost' or _loopback(hostname or ''))


def register(app, policy):
    from flask import jsonify, request

    app.ffado_host = policy.host

    @app.before_request
    def check_access():
        try:
            hostname = urlsplit(request.host_url).hostname
        except ValueError:
            hostname = None
        local = policy.permits_local(request.remote_addr, hostname)
        if not local:
            auth = request.authorization
            if not (policy.token and auth and auth.type.lower() == 'basic'
                    and auth.username == 'ffado'
                    and compare_digest((auth.password or '').encode(), policy.token.encode())):
                return jsonify(error='Mixer access requires authentication'), 401, {
                    'WWW-Authenticate': 'Basic realm="FFADO WebMixer", charset="UTF-8"',
                }

        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            # Browser credentials (including cached Basic auth) are ambient.
            # Validate the origin even for loopback requests and reject simple
            # form submissions to JSON APIs. Native API clients omit Origin.
            origin = request.headers.get('Origin')
            if (request.headers.get('Sec-Fetch-Site') == 'cross-site'
                    or (origin is not None and origin != request.host_url.rstrip('/'))):
                return jsonify(error='Cross-origin mixer writes are forbidden'), 403
            if request.path.startswith('/api/') and not request.is_json:
                return jsonify(error='Mixer writes require application/json'), 415
        return None

    @app.after_request
    def access_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        return response
