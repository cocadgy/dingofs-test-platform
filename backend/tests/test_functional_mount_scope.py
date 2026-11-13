import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
from types import SimpleNamespace

import pytest

from dingofs_platform.functional.preflight import READ_ONLY_PROBE


@pytest.mark.parametrize('location,kind,expected', [
    ('old-child', 'fuse.dingofs', True),
    ('similar-sibling', 'fuse.dingofs', True),
    ('exact', 'fuse.dingofs', False),
    ('ancestor', 'fuse.dingofs', False),
    ('ancestor', 'xfs', True),
])
def test_residual_mounts_only_block_overlapping_test_roots(tmp_path, monkeypatch, capsys,
                                                        location, kind, expected):
    root = tmp_path / 'clients'
    root.mkdir()
    target = {'old-child': root / 'old-quota-test',
              'similar-sibling': tmp_path / 'clients-old',
              'exact': root, 'ancestor': tmp_path}[location]
    original = Path.iterdir
    monkeypatch.setattr(Path, 'iterdir', lambda p: iter(()) if str(p) == '/proc' else original(p))
    def query(argv, **kwargs):
        assert argv == ['findmnt', '--json', '--output', 'ID,TARGET,SOURCE,FSTYPE']
        return SimpleNamespace(returncode=0, stderr='', stdout=json.dumps({'filesystems': [
            {'id': 42, 'target': str(target), 'source': 'DingoFS:old', 'fstype': kind}]}))
    monkeypatch.setattr(subprocess, 'run', query)
    request = {'user': pwd.getpwuid(os.geteuid()).pw_name, 'tools': [], 'binaries': [],
               'paths': [str(root)], 'ports': [], 'cache': False, 'client': False,
               'fs_query': [], 'mount_roots': [str(root)], 'mds': 'node.test:6900'}
    monkeypatch.setattr(sys, 'argv', ['probe', json.dumps(request)])
    exec(compile(READ_ONLY_PROBE, '<read-only probe>', 'exec'), {})
    assert json.loads(capsys.readouterr().out)['checks']['mount_identity'] is expected
