"""Optional output geometry/meter check using the desktop app's Qt WebEngine.

Run with the project interpreter: tests/verify_output_stereo_browser.py.
The shared browser fixture is also runnable in Chromium/Brave via Node.
"""
import os
from pathlib import Path
import subprocess
import tempfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QTWEBENGINE_DISABLE_SANDBOX', '1')
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--no-sandbox --disable-gpu --disable-dev-shm-usage')

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication


def main():
    with tempfile.TemporaryDirectory(prefix='ffado-output-qt-') as directory:
        target = Path(directory) / 'index.html'
        fixture = Path(__file__).with_name('output_stereo_browser_test.cjs')
        subprocess.run(['node', str(fixture)], check=True,
                       env={**os.environ, 'FFADO_OUTPUT_UI_HTML': str(target)})
        app = QApplication(['ffado-output-ui'])
        view = QWebEngineView()
        view.resize(1200, 900)
        view.show()
        result = 2

        def accept(value):
            nonlocal result
            if value and (value == 'OUTPUT_STEREO_BROWSER_PASSED' or value.startswith('FAILED:')):
                print(value, flush=True)
                result = 0 if value == 'OUTPUT_STEREO_BROWSER_PASSED' else 1
                app.quit()

        timer = QTimer()
        timer.timeout.connect(lambda: view.page().runJavaScript(
            "document.getElementById('result')?.textContent || ''", accept))
        timer.start(100)
        QTimer.singleShot(12000, app.quit)
        view.load(QUrl.fromLocalFile(str(target)))
        app.exec()
        return result


if __name__ == '__main__':
    raise SystemExit(main())
