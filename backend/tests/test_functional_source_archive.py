"""Archive namespace and byte/permission limits, independent of current source."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from dingofs_platform.functional.source_archive import manifest_key, resolve_archive


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / 'archives'
    root.mkdir(mode=0o700)
    manifest = {'src/example.py': hashlib.sha256(b'approved bytes').hexdigest()}
    key = manifest_key(manifest)
    source = root / key / 'source'
    (source / 'src').mkdir(parents=True)
    path = source / 'src/example.py'
    path.write_bytes(b'approved bytes')
    path.chmod(0o400)
    for directory in (source / 'src', source, source.parent): directory.chmod(0o500)
    yield root, manifest, source
    for directory in (source.parent, source, source / 'src'):
        if directory.exists(): directory.chmod(0o700)


def test_deployment_cli_key_and_verify_use_the_report_namespace(archive, tmp_path):
    root, manifest, source = archive
    private_manifest = tmp_path / 'manifest.json'
    private_manifest.write_text(json.dumps(manifest))
    expected = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    for action in ('key', 'verify'):
        result = subprocess.run([sys.executable, '-B', '-m', 'dingofs_platform.functional.source_archive', action,
            '--manifest', str(private_manifest), '--archive', str(root)],
            env={**os.environ, 'PYTHONPATH': str(Path(__file__).parents[1] / 'src')},
            capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected
    assert resolve_archive(root, manifest) == source


@pytest.mark.parametrize('name', ['../escape.py', '/absolute.py', 'src//file.py', 'src/./file.py',
                                  'src/\\file.py', 'src/__pycache__/file.pyc', 'bad\nfile', 'code.pyc'])
def test_archive_rejects_manifest_path_and_bytecode_bypasses(name):
    with pytest.raises(ValueError): manifest_key({name: 'a' * 64})


@pytest.mark.parametrize('damage', ['root_permissions', 'root_link', 'root_escape', 'entry_link', 'file_owner', 'oversized'])
def test_archive_refuses_untrusted_paths_owners_and_size(archive, tmp_path, monkeypatch, damage):
    root, manifest, source = archive
    path = source / 'src/example.py'
    if damage == 'root_permissions': root.chmod(0o755)
    if damage == 'root_link':
        link = tmp_path / 'link'
        link.symlink_to(root)
        root = link
    if damage == 'root_escape': root = root / '..' / 'archives'
    if damage == 'entry_link':
        entry = source.parent
        renamed = root / 'retained'
        entry.rename(renamed)
        entry.symlink_to(renamed)
    if damage == 'file_owner':
        original = Path.lstat
        def changed_owner(value):
            info = original(value)
            fields = list(info)
            if value == path: fields[4] = os.geteuid() + 10000
            return os.stat_result(fields)
        monkeypatch.setattr(Path, 'lstat', changed_owner)
    if damage == 'oversized':
        monkeypatch.setattr('dingofs_platform.functional.source_archive.MAX_FILE_BYTES', 4)
    with pytest.raises((ValueError, OSError)): resolve_archive(root, manifest)
