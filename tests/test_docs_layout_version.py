"""Verify documentation organization and the development branch's version."""

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'


def test_root_keeps_only_readme_markdown():
    assert sorted(p.name for p in ROOT.glob('*.md')) == ['README.md']
    assert (DOCS / 'README.md').is_file()
    assert (DOCS / 'CHANGELOG.md').is_file()
    assert (DOCS / 'TESTING.md').is_file()
    import zipfile
    with zipfile.ZipFile(ROOT / 'docs_legacy.zip') as archive:
        assert len([name for name in archive.namelist()
                    if name.startswith('docs/TESTING_') and name.endswith('.md')]) >= 17


def test_version_is_120_without_release_suffix():
    from ffado_webmixer import __version__
    from ffado_webmixer.main import APP_VERSION
    assert APP_VERSION == __version__ == '1.2.0'
    metadata = (ROOT / 'pyproject.toml').read_text()
    assert 'version = {attr = "ffado_webmixer.__version__"}' in metadata
    result = subprocess.run([sys.executable, str(ROOT / 'main.py'), '--version'],
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == 'ffado-webmixer 1.2.0'


def test_markdown_links_still_resolve_after_move():
    for document in [ROOT / 'README.md', *DOCS.glob('*.md')]:
        content = document.read_text(encoding='utf-8')
        for raw in re.findall(r'(?<!!)\[[^]]*\]\(([^)]+)\)', content):
            link = raw.split('#', 1)[0].split('?', 1)[0]
            if not link or '://' in link or link.startswith(('mailto:', '#')):
                continue
            if link.startswith('<') and link.endswith('>'):
                link = link[1:-1]
            target = document.parent / unquote(link)
            assert target.exists(), f'{document.relative_to(ROOT)} -> {raw}'


def test_changelog_preserves_110_dev_history_and_111_entry():
    text = (DOCS / 'CHANGELOG.md').read_text()
    assert '1.1.1 — development branch' in text
    assert '1.1.0-dev — previous development work' in text


def test_docs_upgrade_only_removes_unchanged_guides(tmp_path, monkeypatch):
    import hashlib
    import importlib.util
    helper = ROOT / 'tools' / 'migrate_legacy_docs.py'
    spec = importlib.util.spec_from_file_location('migrate_legacy_docs', helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs' / 'CHANGELOG.md').write_text('upgraded')
    unchanged = 'TESTING_OLD.md'
    modified = 'TESTING_MODIFIED.md'
    originals = {unchanged: b'original', modified: b'original'}
    monkeypatch.setattr(module, 'BASELINE_HASHES', {
        name: hashlib.sha256(data).hexdigest() for name, data in originals.items()
    })
    (tmp_path / 'docs' / unchanged).write_text('new doc')
    (tmp_path / 'docs' / modified).write_text('new doc')
    (tmp_path / unchanged).write_bytes(b'original')
    (tmp_path / modified).write_bytes(b'original with my custom changes')
    module.main()
    assert not (tmp_path / unchanged).exists()
    assert (tmp_path / modified).read_bytes() == b'original with my custom changes'
    module.main()  # idempotent
