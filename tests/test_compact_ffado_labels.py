"""Hardware names remain intact; only the browser abbreviates known labels."""
from pathlib import Path
import ast
import re
import json
import shutil
import subprocess

import pytest

def pair_name(a, b):
    """Run only the real pure pair_name helper, without importing Flask."""
    module = Path(__file__).resolve().parents[1] / 'src/ffado_webmixer/services/stereo.py'
    tree = ast.parse(module.read_text(encoding='utf-8'))
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == 'pair_name')
    namespace = {'re': re}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(module), 'exec'), namespace)
    return namespace['pair_name'](a, b)


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js is needed for browser label checks')
def test_original_ffado_pair_names_are_shortened_without_rewriting_hardware_ids():
    examples = {
        pair_name('1394/In:01', '1394/In:02'): 'Firewire 1+2',
        pair_name('1394/In:02', '1394/In:01'): 'Firewire 2+1',
        pair_name('Mic/Lin/Inst:03', 'Mic/Lin/Inst:04'): 'Analog 3+4',
        pair_name('Mic/Lin/In:03', 'Mic/Lin/In:04'): 'Analog 3+4',
        'Mic/Lin/In:05': 'Analog 5',
        'Mic/Lin/In:06': 'Analog 6',
        'Mic/Lin/In:07': 'Analog 7',
        'Mic/Lin/In:08': 'Analog 8',
        pair_name('1394/In:02', 'SPDIF/In:01'): 'Firewire 2 + SPDIF 1',
        '1394/In:01 + 1394/In:02': 'Firewire 1+2',
        'Vocals 1 + Vocals 2': 'Vocals 1 + Vocals 2',
    }
    assert pair_name('1394/In:01', '1394/In:02') == '1394/In:01+02'
    script = (
        'const short = require(' + json.dumps(str(Path(__file__).resolve().parents[1] / 'src/ffado_webmixer/assets/static/labels.js')) + ');'
        'const values = JSON.parse(process.argv[1]);'
        'process.stdout.write(JSON.stringify(values.map(x => short(x))));'
    )
    result = subprocess.run(['node', '-e', script, json.dumps(list(examples))],
                            check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == list(examples.values())
