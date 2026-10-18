"""CLI regression tests: --debug always requires a matching profile."""
import subprocess
import sys
import unittest
from pathlib import Path

from ffado_webmixer.debug_backend import resolve_debug_profile

MAIN = Path(__file__).resolve().parents[1] / 'main.py'


class DebugProfileArgumentTests(unittest.TestCase):
    def test_bare_debug_errors_not_defaults(self):
        result = subprocess.run([sys.executable, str(MAIN), '--debug'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('expected one argument', result.stderr)

    def test_debug_list_exits_without_flask_or_dbus(self):
        result = subprocess.run([sys.executable, str(MAIN), '--debug', 'list'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('motuultralite', result.stdout)
        self.assertIn('profire2626', result.stdout)

    def test_aliases(self):
        for alias in ('Motu-Ultralite', 'motu_ultralite', 'MOTU ULTRALITE', 'motu_ultralite.xml'):
            with self.subTest(alias=alias):
                self.assertEqual(resolve_debug_profile(alias), 'motuultralite')
        self.assertEqual(resolve_debug_profile('ProFire 2626'), 'profire2626')

    def test_unknown_profile_exits_before_importing_flask(self):
        result = subprocess.run([sys.executable, str(MAIN), '--debug', 'unlisted-device'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unknown or unsupported debug profile', result.stderr)
        self.assertIn('--debug list', result.stderr)


if __name__ == '__main__':
    unittest.main()
