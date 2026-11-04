"""Exercise the DICE bus/output overview against mocked hardware responses."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_dice_gains_overview():
    if not shutil.which('node'):
        pytest.skip('Node.js is required for the offline UI test')
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ['node', str(root / 'tests' / 'dice_gains_ui_test.cjs')],
        cwd=root, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
