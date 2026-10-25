"""Shared remote-access credentials for the desktop settings and CLI."""
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import warnings

from argon2 import PasswordHasher, Type, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError


_HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, type=Type.ID)
DEFAULT_PORT = 5000
_UNSET = object()


def validate_port(port):
    if isinstance(port, str):
        port = port.strip()
        if not port:
            return DEFAULT_PORT
        if not port.isascii() or not port.isdecimal():
            raise ValueError('Port must be a whole number from 1 to 65535')
        port = int(port)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Port must be a whole number from 1 to 65535')
    return port


def validate_username(username):
    if not isinstance(username, str):
        raise ValueError('Username must be a string')
    username = username.strip()
    if (not 1 <= len(username) <= 64 or ':' in username
            or any(ord(char) < 32 or ord(char) == 127 for char in username)):
        raise ValueError('Username must be 1–64 characters without colons or control characters')
    return username


def validate_password(password):
    if not isinstance(password, str) or len(password.strip()) < 16 or len(password) > 1024:
        raise ValueError('Password must be 16–1024 characters (excluding surrounding spaces from the minimum)')


class RemoteAccessConfig:
    """Keep credentials separate from browser-readable mixer preferences.

    Updates are published to authentication only after an atomic, private save.
    A process-local HMAC remembers the last successful login so Basic auth on
    each fader request does not repeatedly run an expensive password hash.
    """

    def __init__(self, path=None, *, writable=True):
        self.path = Path(path) if path is not None else None
        self.writable = writable
        self.enabled = False
        self.username = ''
        self.port = DEFAULT_PORT
        self._password_hash = ''
        self._lock = threading.RLock()
        self._cache_key = secrets.token_bytes(32)
        self._verified = None
        self._revision = 0
        self._stream_revocations = set()

    @property
    def configured(self):
        return bool(self.username and self._password_hash)

    def load(self):
        if self.path is None:
            return
        try:
            with self.path.open(encoding='utf-8') as stream:
                record = json.load(stream)
        except FileNotFoundError:
            return
        except (ValueError, UnicodeError) as exc:
            raise ValueError('Invalid remote-access configuration; run --enable-remote-access to replace it') from exc
        try:
            if not isinstance(record, dict) or type(record.get('enabled')) is not bool:
                raise ValueError('Invalid enabled flag')
            port = validate_port(record.get('port', DEFAULT_PORT))
            username, password_hash = record.get('username', ''), record.get('password_hash', '')
            if username or password_hash or record['enabled']:
                username = validate_username(username)
                if not isinstance(password_hash, str) or extract_parameters(password_hash).type != Type.ID:
                    raise ValueError('Invalid password hash')
            elif username != '' or password_hash != '':
                raise ValueError('Invalid credentials')
        except (ValueError, TypeError, InvalidHashError) as exc:
            raise ValueError('Invalid remote-access configuration; run --enable-remote-access to replace it') from exc
        with self._lock:
            self._publish(record['enabled'], username, password_hash)
            self.port = port

    def update(self, *, enabled, username, password='', port=_UNSET):
        if not self.writable:
            raise PermissionError('Remote-access settings cannot be changed in demo or debug mode')
        if type(enabled) is not bool or not isinstance(password, str) or not isinstance(username, str):
            raise ValueError('Enabled must be a boolean; username and password must be strings')
        with self._lock:
            port = self.port if port is _UNSET else validate_port(port)
            username = validate_username(username) if username or enabled or password else ''
            password_hash = self._password_hash
            if password:
                validate_password(password)
                password_hash = _HASHER.hash(password)
            if not username:
                password_hash = ''
            if (enabled or username or password_hash) and not (username and password_hash):
                raise ValueError('Set a username and password before saving remote-access credentials')
            record = {'enabled': enabled, 'username': username, 'password_hash': password_hash, 'port': port}
            self._save(record)
            self._publish(enabled, username, password_hash)
            self.port = port

    def _publish(self, enabled, username, password_hash):
        """Publish saved credentials and revoke streams under the same lock."""
        changed = (self.enabled, self.username, self._password_hash) != (enabled, username, password_hash)
        self.enabled, self.username, self._password_hash = enabled, username, password_hash
        self._verified = None
        if changed:
            self._revision += 1
            callbacks = tuple(self._stream_revocations)
            self._stream_revocations.clear()
            for revoke in callbacks:
                revoke()

    def watch_stream(self, revision, revoke):
        with self._lock:
            if not self.enabled or revision != self._revision:
                revoke()
            else:
                self._stream_revocations.add(revoke)

    def unwatch_stream(self, revoke):
        with self._lock:
            self._stream_revocations.discard(revoke)

    def _save(self, record):
        if self.path is None:
            return
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
        fd, temporary = tempfile.mkstemp(prefix='.auth-', suffix='.tmp', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                os.fchmod(stream.fileno(), 0o600)
                json.dump(record, stream, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def authenticate(self, username, password):
        return self.authenticate_revision(username, password) is not None

    def authenticate_revision(self, username, password):
        """Return the credential revision validated by this authentication."""
        if not isinstance(username, str) or not isinstance(password, str) or len(password) > 1024:
            return None
        with self._lock:
            if not self.enabled or not self.configured or username != self.username:
                return None
            proof = hmac.digest(self._cache_key, (username + ':' + password).encode(), hashlib.sha256)
            if self._verified is not None and hmac.compare_digest(proof, self._verified):
                return self._revision
            try:
                _HASHER.verify(self._password_hash, password)
            except (VerificationError, InvalidHashError):
                return None
            self._verified = proof
            return self._revision

    def status(self):
        with self._lock:
            return {'enabled': self.enabled, 'username': self.username, 'configured': self.configured,
                    'port': self.port}


def prompt_remote_access(config):
    """Interactive setup; never accept a password through argv or echo input."""
    try:
        while True:
            try:
                username = validate_username(input('Remote access username: '))
                break
            except ValueError as exc:
                print(exc)
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            while True:
                password = getpass.getpass('Remote access password (at least 16 characters): ')
                try:
                    validate_password(password)
                except ValueError as exc:
                    print(exc)
                    continue
                if password != getpass.getpass('Confirm password: '):
                    print('Passwords do not match; try again.')
                    continue
                break
        while True:
            try:
                port = validate_port(input(f'Remote access port [Enter for {DEFAULT_PORT}]: '))
                break
            except ValueError as exc:
                print(exc)
        config.update(enabled=True, username=username, password=password, port=port)
    except (EOFError, KeyboardInterrupt):
        raise ValueError('Remote access setup cancelled; settings were not changed') from None
    except getpass.GetPassWarning:
        raise ValueError('A terminal with hidden password input is required; settings were not changed') from None
