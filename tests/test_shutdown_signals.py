"""Send real signals only to subprocesses with simulated FFADO hardware."""
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

import pytest


pytestmark = pytest.mark.skipif(os.name != 'posix', reason='POSIX termination signals')

CHILD = r'''
import atexit
import json
import os
from pathlib import Path
import signal
from socketserver import BaseServer
import sys
from types import SimpleNamespace

from ffado_webmixer import main, server
from ffado_webmixer.debug_backend import make_debug_mixer

root, mode = Path(sys.argv[1]), sys.argv[2]
main.CONFIG_DIR = root
main.CONFIG_FILE = root / 'config.json'
main.parse_args = lambda: SimpleNamespace(demo=False, debug=None, headless=True)
state = {'cleanup_calls': 0, 'closed': False}
previous_handler = signal.getsignal(signal.SIGTERM)

def create_backends(args, config):
    mixer = make_debug_mixer('profire2626', config)
    state['mixer'] = mixer
    shutdown = mixer.shutdown_soft_mutes
    def cleanup():
        state['cleanup_calls'] += 1
        state['closed_before_cleanup'] = state['closed']
        if mode == 'repeat':
            os.kill(os.getpid(), signal.SIGTERM)
        shutdown()
    mixer.shutdown_soft_mutes = cleanup
    return [mixer]

main.create_backends = create_backends

def prepare(app):
    mixer = state['mixer']
    state['original'] = [mixer._get_cell(mixer.roles['fader'][0], 0, col)
                         for col in (0, 1)]
    client = app.test_client()
    for col in (0, 1):
        response = client.post('/api/set', json={
            'strip': f'ch/{col:02d}', 'control': 'mute', 'value': True, 'mix': 0})
        assert response.status_code == 200, response.data
    state['journal_before'] = mixer._recovery_journal.path.read_text()
    assert all(mixer._get_cell(mixer.roles['fader'][0], 0, col) == 0 for col in (0, 1))
    if mode == 'failure':
        set_cell = mixer.helper.set_cell
        failed_coordinates = mixer._coordinates(0, 1)
        def refuse_restore(path, row, col, value):
            if (row, col) == failed_coordinates and value != 0:
                raise OSError('simulated restoration failure')
            return set_cell(path, row, col, value)
        mixer.helper.set_cell = refuse_restore
    if mode == 'bind_failure':
        raise RuntimeError('simulated busy port')
    # Exercise the real BaseServer loop without requiring a network listener.
    # Its selector waits on an idle pipe instead of a socket.
    class PipeServer(BaseServer):
        def __init__(self):
            super().__init__(('offline', 0), None)
            self.read_fd, self.write_fd = os.pipe()
        def fileno(self):
            return self.read_fd
        def server_close(self):
            os.close(self.read_fd)
            os.close(self.write_fd)
    listener = PipeServer()
    serve, close = listener.serve_forever, listener.server_close
    def serve_forever():
        print('READY', flush=True)
        if mode != 'return':
            serve()
    def server_close():
        close()
        state['closed'] = True
    listener.serve_forever = serve_forever
    listener.server_close = server_close
    return listener

server.prepare_server = prepare

def report():
    mixer = state['mixer']
    journal = mixer._recovery_journal
    print('REPORT ' + json.dumps({
        'cleanup_calls': state['cleanup_calls'], 'closed': state['closed'],
        'closed_before_cleanup': state['closed_before_cleanup'],
        'handler_restored': signal.getsignal(signal.SIGTERM) == previous_handler,
        'original': state['original'],
        'levels': [mixer._get_cell(mixer.roles['fader'][0], 0, col) for col in (0, 1)],
        'journal_path': str(journal.path),
        'journal_before': json.loads(state['journal_before']),
        'journal_after': json.loads(journal.path.read_text()) if journal.path.exists() else None,
    }), flush=True)

atexit.register(report)
main.main()
'''


def run_child(tmp_path, mode, termination=None):
    env = dict(os.environ, HOME=str(tmp_path / 'home'),
               XDG_CACHE_HOME=str(tmp_path / 'cache'),
               PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
    child = subprocess.Popen([sys.executable, '-u', '-c', CHILD, str(tmp_path), mode],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=env)
    before = b''
    try:
        if termination is not None:
            deadline = time.monotonic() + 15
            while True:
                remaining = deadline - time.monotonic()
                assert remaining > 0, 'child never reached its serving loop'
                assert select.select([child.stdout], [], [], remaining)[0], 'child startup timed out'
                chunk = os.read(child.stdout.fileno(), 65536)
                assert chunk, (before.decode(), child.stderr.read().decode())
                before += chunk
                if b'READY\n' in before:
                    break
            child.send_signal(termination)
        stdout, stderr = child.communicate(timeout=15)
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)
    output = (before + stdout).decode()
    stderr = stderr.decode()
    expected_code = (1 if mode == 'bind_failure' else
                     -signal.SIGINT if termination == signal.SIGINT else 0)
    assert child.returncode == expected_code, (output, stderr)
    reports = [line.removeprefix('REPORT ') for line in output.splitlines() if line.startswith('REPORT ')]
    assert len(reports) == 1, (output, stderr)
    return json.loads(reports[0])


@pytest.mark.parametrize('mode,termination', [
    ('signal', signal.SIGTERM), ('repeat', signal.SIGTERM),
    ('signal', signal.SIGINT), ('return', None), ('bind_failure', None),
])
def test_shutdown_restores_muted_levels_once_and_releases_listener(tmp_path, mode, termination):
    result = run_child(tmp_path, mode, termination)
    assert result['cleanup_calls'] == 1
    assert result['closed'] is (mode != 'bind_failure')
    assert result['closed_before_cleanup'] is (mode != 'bind_failure')
    assert result['handler_restored']
    assert result['levels'] == result['original']
    assert result['journal_after'] is None
    assert not Path(result['journal_path']).exists()


def test_sigterm_keeps_only_failed_restorations_in_recovery_journal(tmp_path):
    result = run_child(tmp_path, 'failure', signal.SIGTERM)
    assert result['cleanup_calls'] == 1
    assert result['closed']
    assert result['closed_before_cleanup']
    assert result['handler_restored']
    assert result['levels'] == [result['original'][0], 0]
    failed = result['journal_before']['levels'][1]
    assert result['journal_after']['levels'] == [failed]
    assert json.loads(Path(result['journal_path']).read_text()) == result['journal_after']
