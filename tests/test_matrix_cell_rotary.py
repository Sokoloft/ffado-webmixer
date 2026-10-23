"""Matrix-cell rotary UI integration and dependency-free JavaScript behavior."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'src/ffado_webmixer' / 'assets' / 'static'


def test_matrix_cell_controls_are_inline_and_existing_editor_is_retained():
    js = (STATIC / 'routing.js').read_text(encoding='utf8')
    css = (STATIC / 'routing.css').read_text(encoding='utf8')
    html = (STATIC / 'index.html').read_text(encoding='utf8')
    assert 'installMatrixKnob(cell, i, o)' in js
    assert 'paintMatrixCell(cell, val, db)' in js
    assert 'role\', \'slider' in js
    assert 'matrixWriteBusy' in js
    assert 'matrixWriteEpoch' in js
    assert '.matrix-cell-dial' in css
    assert '.matrix-cell-needle' in css
    assert 'id="routingEditor"' in html
    assert 'id="routingDb"' in html
    assert 'id="routingPreset"' in html
    assert 'id="routingApply"' in html
    # Writing one cell must never imply writes to any other route.
    assert "request('/api/matrix', payload)" in js
    assert 'input: gesture.input, output: gesture.output' in js


def test_rotary_gestures_and_hardware_readback_in_node():
    if not shutil.which('node'):
        pytest.skip('Node.js is only used for the optional offline UI test')
    result = subprocess.run(
        ['node', str(ROOT / 'tests' / 'matrix_cell_rotary_ui_test.cjs')],
        cwd=ROOT, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Matrix-cell rotary UI:' in result.stdout
