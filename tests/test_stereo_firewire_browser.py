"""Run the tiny dependency-free browser interaction test when Node is present."""
from pathlib import Path
import shutil
import subprocess
import pytest


def test_stereo_firewire_browser_control():
    if not shutil.which('node'):
        pytest.skip('Node only used for optional browser UI regression')
    script = Path(__file__).with_name('stereo_firewire_ui_test.cjs')
    run = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=20)
    assert run.returncode == 0, run.stdout + run.stderr
