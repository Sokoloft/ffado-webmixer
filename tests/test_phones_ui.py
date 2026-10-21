"""Exercise browser routing changes without a browser or npm packages."""
from pathlib import Path
import subprocess


def test_phones_assignment_ui_node():
    path = Path(__file__).with_name('phones_assignment_ui_test.cjs')
    result = subprocess.run(['node', str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'MOTU Phones UI' in result.stdout
