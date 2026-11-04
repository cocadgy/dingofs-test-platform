from copy import deepcopy
from types import SimpleNamespace

import pytest

from dingofs_platform.resources import external_mount as external
from dingofs_platform.resources import remote_helper as helper


@pytest.fixture
def host(monkeypatch):
    identity = dict(pid=123, start_ticks='17', exe='/opt/dingo-client', mount_id='42', namespace='mnt:[1]')
    process = dict(pid=123, start_ticks='17', exe='/opt/dingo-client',
                   argv=['/opt/dingo-client', 'mds://a:6900/manual', '/mnt/manual', '--log_dir=/tmp/manual-logs'])
    mount = dict(mount_id='42', fs_type='fuse.dingofs', source='DingoFS:manual', mount_path='/mnt/manual')
    host = SimpleNamespace(identity=identity, process=process, mount=mount, state={}, commands=[])
    class Store:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def load(self): return deepcopy(host.state)
        def save(self, value): host.state = deepcopy(value)
    monkeypatch.setattr(helper, 'OwnedState', Store)
    monkeypatch.setattr(external.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(external.os, 'readlink', lambda p: 'mnt:[1]')
    monkeypatch.setattr(helper, 'mount_identity', lambda p: host.mount)
    monkeypatch.setattr(helper, 'process_identity', lambda p: host.process)
    monkeypatch.setattr(external, '_external_capture', lambda p, r: dict(argv=p['argv'], user='jenkins', cwd='/home/jenkins', env={}))
    def command(argv, **kw):
        host.commands.append(argv)
        host.mount = None
        host.process = None
    monkeypatch.setattr(helper, 'run_command', command)
    host.req = dict(action='mount.unmount', mds_addr='a:6900', resource_id='saved', parameters={},
        record=dict(origin='external', identity=identity, mount_path='/mnt/manual', fs_name='manual',
                    client_user='jenkins', state_dir='/tmp/platform-state', log_dir='/tmp/manual-logs'))
    return host


def test_external_unmount_preserves_restart_arguments_and_uses_exact_path(host):
    state, data = external.external_mount_lifecycle(host.req, helper)
    assert state == 'unmounted'
    assert host.commands == [['umount', '-l', '--', '/mnt/manual']]
    assert host.state['launch']['user'] == 'jenkins'
    assert 'argv' not in data


@pytest.mark.parametrize('changed', ['mount', 'process', 'cluster'])
def test_replaced_mount_or_process_is_not_unmounted(host, changed):
    if changed == 'mount': host.mount['mount_id'] = '99'
    if changed == 'process': host.process['start_ticks'] = '99'
    if changed == 'cluster': host.process['argv'][1] = 'mds://foreign:6900/manual'
    with pytest.raises(ValueError):
        external.external_mount_lifecycle(host.req, helper)
    assert host.commands == []


def test_external_remount_after_unmount_reuses_original_account_and_arguments(host, monkeypatch):
    external.external_mount_lifecycle(host.req, helper)
    launched = []
    new_identity = {**host.identity, 'pid': 456, 'start_ticks': '28', 'mount_id': '43'}
    def launch(req, h, config):
        launched.append(config)
        host.process = dict(pid=456, start_ticks='28', exe='/opt/dingo-client', argv=config['argv'])
        host.mount = dict(mount_id='43', fs_type='fuse.dingofs', source='DingoFS:manual')
    monkeypatch.setattr(external, '_external_launch', launch)
    monkeypatch.setattr(helper, 'scan_mounts', lambda m: {'mounts': [dict(mount_path='/mnt/manual',
        cluster_match='current', fs_name='manual', identity=new_identity)]})
    state, data = external.external_mount_lifecycle({**host.req, 'action': 'mount.remount'}, helper)
    assert state == 'mounted' and not data['hot_updated']
    assert launched[0]['user'] == 'jenkins'
    assert launched[0]['argv'][1] == 'mds://a:6900/manual'
    assert host.state['identity'] == new_identity


def test_capture_during_scan_keeps_arguments_on_host_not_in_scan_response(host):
    row = dict(identity=host.identity, mount_path='/mnt/manual', fs_name='manual', client_user='jenkins', cluster_match='current')
    req = dict(mds_addr='a:6900', record=dict(cluster_id='cluster', external_mounts=[]))
    result = external.capture_external_mounts(req, {'mounts': [row]}, helper)
    assert result['mounts'][0]['adopted_resource_id']
    assert 'argv' not in result['mounts'][0]
    assert host.state['launch']['argv'][1] == 'mds://a:6900/manual'
