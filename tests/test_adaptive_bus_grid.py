"""Ensure high-bus-count devices can grow the right-side bus picker leftward."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / 'src/ffado_webmixer/assets/static/index.css').read_text()
JS = (ROOT / 'src/ffado_webmixer/assets/static/index.js').read_text()


def test_bus_grid_scopes_columns_to_bus_buttons_only():
    assert '" bus-group"' in JS
    assert '" busgrid"' in JS
    assert 'busCount <= 8' in JS  # UltraLite and other small mixers cap at two
    assert 'grid.style.setProperty("--cols", String(selected))' in JS
    assert '#side.narrow .groupgrid { --cols: 1 !important; }' in CSS
    assert '.bus-pair-tile { display: grid; grid-column: span 2; grid-row: span 2;' in CSS
    assert '#side.narrow .bus-pair-tile { grid-column: 1; grid-row: span 3;' in CSS
    assert '.bus-pair-link { grid-column:1 / -1;' in CSS
    assert 'tile.appendChild(makeOutputButton(left));' in JS
    assert 'tile.appendChild(makeOutputButton(right));' in JS
    assert 'tile.appendChild(makeBusLink(leftMix));' in JS
    assert 'scheduleBusGridLayout();' in JS
    assert 'ResizeObserver' in JS


def test_bus_grid_ui_behavior():
    if not shutil.which('node'):
        pytest.skip('Node.js is only needed for optional frontend regression tests')
    test = ROOT / 'tests/adaptive_bus_grid_ui_test.cjs'
    result = subprocess.run(['node', str(test)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
