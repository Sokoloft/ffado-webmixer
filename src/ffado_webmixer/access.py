"""Listener policy and browser request checks for local and LAN control."""
from dataclasses import dataclass, field
from ipaddress import ip_address
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from .remote_access import RemoteAccessConfig


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
    remote_access: 'RemoteAccessConfig | None' = field(default=None, repr=False)

    def __post_init__(self):
        object.__setattr__(self, 'host', bind_address(self.host))
        if not _loopback(self.host) and not (
                self.remote_access and self.remote_access.enabled and self.remote_access.configured):
            raise ValueError('LAN access requires a saved username and password; run --enable-remote-access first')

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
            revision = None
            if policy.remote_access and auth and auth.type.lower() == 'basic':
                revision = policy.remote_access.authenticate_revision(auth.username, auth.password or '')
            if revision is None:
                return jsonify(error='Mixer access requires authentication'), 401, {
                    'WWW-Authenticate': 'Basic realm="FFADO WebMixer", charset="UTF-8"',
                }
            request.environ['ffado_webmixer.remote_authorization'] = (policy.remote_access, revision)

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

    # Remote users can operate the mixer, but credential management stays local.
    @app.get('/api/remote-access')
    def remote_access_status():
        local = policy.permits_local(request.remote_addr, urlsplit(request.host_url).hostname)
        config = policy.remote_access
        status = config.status() if config else {'enabled': False, 'username': '', 'configured': False}
        return jsonify(**status, can_manage=bool(local and config and config.writable),
                       listening=not _loopback(policy.host),
                       restart_required=status['enabled'] != (not _loopback(policy.host)))

    @app.post('/api/remote-access')
    def update_remote_access():
        if not policy.permits_local(request.remote_addr, urlsplit(request.host_url).hostname):
            return jsonify(error='Manage remote access from the local application or localhost browser'), 403
        config = policy.remote_access
        if config is None or not config.writable:
            return jsonify(error='Remote-access settings cannot be changed in demo or debug mode'), 403
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error='Remote-access settings must be a JSON object'), 400
        try:
            config.update(enabled=payload.get('enabled'), username=payload.get('username'),
                          password=payload.get('password', ''))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except OSError:
            return jsonify(error='Could not save remote-access settings; previous settings remain active'), 500
        return remote_access_status()
