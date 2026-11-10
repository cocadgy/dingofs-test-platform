"""Execute the actual read-only residual probe against isolated local fixtures."""
import json
from types import SimpleNamespace

import pytest


def request(kind='directory', path='/tmp/test-exact'):
    return {'child_id': 'child', 'resource_id': 'resource', 'kind': kind,
        'expected_identity': {'device_inode': '1:2'}, 'target': {'cluster': 'mds:6900',
            'host': 'node', 'user': 'test', 'name': 'exact', 'path': path, 'port': None}, 'dingo': '/opt/dingo'}


def test_directory_probe_checks_identity_and_absence_without_following_symlinks(tmp_path):
    from dingofs_platform.functional.retention_probe import probe
    path = tmp_path / 'owned'
    path.mkdir()
    row = request(path=str(path))
    observed = probe(row)
    assert observed['status'] == 'present'
    assert observed['identity'] == {'device_inode': f'{path.stat().st_dev}:{path.stat().st_ino}'}
    path.rmdir()
    assert probe(row)['status'] == 'absent'
    path.symlink_to(tmp_path)
    assert probe(row)['status'] == 'unknown'


@pytest.mark.parametrize('body,want', [({'result': {'fs_infos': []}}, 'absent'),
    ({'result': {'fs_infos': [{'fs_name': 'exact', 'fs_id': 7}]}}, 'present'),
    ({'unexpected': []}, 'unknown'), ({'result': {'fs_infos': [{'fs_name': 'exact'}]}}, 'unknown')])
def test_filesystem_absence_requires_recognized_complete_schema(monkeypatch, body, want):
    import subprocess
    from dingofs_platform.functional.retention_probe import probe
    calls = []
    def run(argv, **kwargs):
        assert argv == ['/opt/dingo', 'fs', 'list', '--mdsaddr', 'mds:6900', '--format', 'json']
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=json.dumps(body), stderr='')
    monkeypatch.setattr(subprocess, 'run', run)
    observed = probe(request('filesystem'))
    assert observed['status'] == want and calls
    if want == 'present':
        assert observed['identity'] == {'fs_id': '7'}


@pytest.mark.parametrize('kind', ['mount', 'cache'])
def test_absent_mount_or_cache_requires_both_registration_and_process_absence(monkeypatch, kind):
    import subprocess
    from dingofs_platform.functional import retention_probe as module
    row = request(kind)
    def run(argv, **kwargs):
        if argv[0] == 'findmnt':
            assert argv == ['findmnt', '--json', '--mountpoint', '/tmp/test-exact', '--output', 'ID,TARGET,SOURCE,FSTYPE']
            return SimpleNamespace(returncode=1, stdout='', stderr='')
        assert argv == ['/opt/dingo', 'cache', 'member', 'list', '--mdsaddr', 'mds:6900', '--format', 'json']
        return SimpleNamespace(returncode=0, stdout='{"result":{"members":[]}}', stderr='')
    monkeypatch.setattr(subprocess, 'run', run)
    monkeypatch.setattr(module, 'processes', lambda *args: [])
    assert module.probe(row)['status'] == 'absent'
    monkeypatch.setattr(module, 'processes', lambda *args: [{'pid': 123, 'start': '456'}])
    assert module.probe(row)['status'] == 'unknown'


def test_stopped_cache_probe_keeps_exact_registration_identity(monkeypatch):
    import subprocess
    from dingofs_platform.functional import retention_probe as module
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0,
        stdout='{"result":{"members":[{"member_id":"exact","group_name":"group","ip":"192.0.2.1","port":12000}]}}', stderr=''))
    monkeypatch.setattr(module, 'processes', lambda *args: [])
    observed = module.probe(request('cache'))
    assert observed['status'] == 'present'
    assert observed['identity'] == {'member_id': 'exact', 'group_name': 'group', 'ip': '192.0.2.1', 'port': 12000, 'process': None}


@pytest.mark.parametrize('changed', [None, 'executable', 'positional_path', 'owner'])
def test_mount_process_matches_actual_owned_resources_schema(tmp_path, monkeypatch, changed):
    import pwd
    from pathlib import Path
    from dingofs_platform.functional import retention_probe as module
    proc = tmp_path / 'proc'
    entry = proc / '123'
    entry.mkdir(parents=True)
    argv = ['/opt/dingo-client', '--mountpoint=/tmp/test-exact', '--fsname=exact', '--mdsaddr=mds:6900']
    if changed == 'positional_path':
        argv = ['/opt/dingo-client', '--log_dir', '/tmp/test-exact', '--fsname=exact', '--mdsaddr=mds:6900']
    (entry / 'cmdline').write_bytes(b'\0'.join(arg.encode() for arg in argv))
    (entry / 'stat').write_text('123 (client) S ' + ' '.join(['0'] * 18 + ['456']))
    (entry / 'exe').symlink_to('/opt/not-a-client' if changed == 'executable' else '/opt/dingo-client')
    monkeypatch.setattr(module, 'Path', lambda path: proc if path == '/proc' else Path(path))
    monkeypatch.setattr(pwd, 'getpwuid', lambda uid: SimpleNamespace(pw_name='another' if changed == 'owner' else 'test'))
    if changed:
        with pytest.raises(ValueError):
            module.processes('mount', request('mount')['target'])
    else:
        assert module.processes('mount', request('mount')['target']) == [{'pid': 123, 'start_time': '456',
            'exe': '/opt/dingo-client', 'fs_name': 'exact', 'mds_addr': 'mds:6900', 'mount_path': '/tmp/test-exact'}]


def test_missing_registration_does_not_hide_live_original_process_with_changed_argv(tmp_path, monkeypatch):
    from pathlib import Path
    from dingofs_platform.functional import retention_probe as module
    proc = tmp_path / 'proc'
    entry = proc / '123'
    entry.mkdir(parents=True)
    (entry / 'cmdline').write_bytes(b'/opt/dingo-cache\0--id=changed')
    (entry / 'stat').write_text('123 (cache) S ' + ' '.join(['0'] * 18 + ['456']))
    (entry / 'exe').symlink_to('/opt/dingo-cache')
    monkeypatch.setattr(module, 'Path', lambda path: proc if path == '/proc' else Path(path))
    row = request('cache')
    row['registration'] = {'members': []}
    row['expected_identity'] = {'process': {'pid': 123, 'start': '456', 'exe': '/opt/dingo-cache', 'member_id': 'exact'}}
    assert module.probe(row)['status'] == 'unknown'
