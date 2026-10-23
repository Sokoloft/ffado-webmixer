"""Offline checks for the 1.0.1 About / QR-code experience."""
import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/ffado_webmixer" / "assets" / "static"


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = {}

    def handle_starttag(self, tag, attrs):
        props = dict(attrs)
        if "id" in props:
            assert props["id"] not in self.ids
            self.ids[props["id"]] = (tag, props)


def test_version_is_full_semver_string():
    from ffado_webmixer import __version__
    from ffado_webmixer.main import APP_VERSION
    assert APP_VERSION == __version__ == '1.2.0'


def test_about_has_qr_button_and_replacement_dialog():
    html = (STATIC / "index.html").read_text()
    parser = Elements()
    parser.feed(html)
    assert parser.ids['aboutShowQR'][0] == 'button'
    assert parser.ids['aboutOpenMixer'][0] == 'a'
    about = html.split('id="pane-about"', 1)[1].split('</dl>', 1)[0]
    assert about.index('id="aboutOpenMixer"') < about.index('id="aboutShowQR"')
    assert 'hidden' in parser.ids['qrDialog'][1]
    assert 'aria-modal' in parser.ids['qrDialog'][1]
    assert parser.ids['qrClose'][0] == 'button'
    assert html.index('/static/qrcode.js') < html.index('/static/index.js')
    assert (STATIC / 'QR-LICENSE.txt').exists()


def test_qr_generator_encodes_lan_urls_without_external_network():
    if not shutil.which('node'):
        return  # Browser implementation can be tested manually if Node is absent.
    src = STATIC / 'qrcode.js'
    js = f'''
    const fs = require("fs"), vm = require("vm");
    const context = {{window: {{}}}};
    vm.runInNewContext(fs.readFileSync({json.dumps(str(src))}, "utf8"), context);
    const QR = context.window.FFADOQRCode;
    for (const url of ["http://192.168.1.15:5000/", "http://10.0.0.22:5000/"]) {{
      const code = new QR.Code(0, QR.Ecc.M);
      code.addData(url);
      code.make();
      if (code.getModuleCount() < 21) throw Error('Bad QR dimensions');
      if (!code.isDark(0,0)) throw Error('Missing top left QR finder');
    }}
    '''
    subprocess.run(['node', '-e', js], check=True, capture_output=True, text=True)


def test_qr_close_restores_about_without_closing_settings():
    js = (STATIC / "index.js").read_text()
    assert 'function closeMixerQR()' in js
    method = js.split('function closeMixerQR() {', 1)[1].split('\n}', 1)[0]
    assert 'qrDialog.hidden = true' in method
    assert 'dialog.hidden = false' in method
    assert 'aboutShowQR.focus()' in method
    close = js.split('function closeSettings() {', 1)[1].split('\n}', 1)[0]
    assert 'closeMixerQR(); return;' in close
