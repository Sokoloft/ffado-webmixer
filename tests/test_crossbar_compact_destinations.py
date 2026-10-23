"""Crossbar destination titles use human names but still write FFADO IDs."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js is needed for browser rendering checks')
def test_crossbar_compact_group_and_row_labels():
    test = Path(__file__).with_name('crossbar_compact_destinations_ui_test.cjs')
    result = subprocess.run(['node', str(test)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
