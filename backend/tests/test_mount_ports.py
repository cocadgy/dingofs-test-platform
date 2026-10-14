import socket

import pytest

from dingofs_platform.resources import remote_helper as helper


def test_mount_port_skips_occupied_default_and_updates_command():
    with socket.socket() as occupied:
        occupied.bind(('0.0.0.0', 10000))
        occupied.listen()
        request = {'record': {'mount_options': {}}}
        port = helper.select_mount_port(request)
        assert 10001 <= port <= 19999
        request['record'].update(fs_name='fs', mount_path='/tmp/mount', log_dir='/tmp/log')
        request['mds_addr'] = 'mds:6900'
        request['record']['mount_options']['vfs_dummy_server_port'] = str(port)
        assert '--vfs_dummy_server_port=' + str(port) in helper.mount_argv(request)


def test_mount_port_honors_free_configured_port_and_replaces_busy_one():
    with socket.socket() as free:
        free.bind(('0.0.0.0', 0))
        port = free.getsockname()[1]
    assert helper.select_mount_port({'record': {'mount_options': {'vfs_dummy_server_port': str(port)}}}) == port
    with socket.socket() as occupied:
        occupied.bind(('0.0.0.0', port))
        occupied.listen()
        assert helper.select_mount_port({'record': {'mount_options': {'vfs_dummy_server_port': str(port)}}}) != port


def test_mount_port_exhaustion_is_explicit(monkeypatch):
    monkeypatch.setattr(helper, 'port_busy', lambda port: True)
    with pytest.raises(ValueError, match='可用端口'):
        helper.select_mount_port({'record': {'mount_options': {}}})


def test_mount_start_selects_port_before_launch_and_persists_it(tmp_path, monkeypatch):
    request = {
        'action': 'mount.create', 'resource_id': 'resource', 'mds_addr': 'mds:6900',
        'record': {
            'state_dir': str(tmp_path / 'state'),
            'log_dir': str(tmp_path / 'logs'),
            'mount_path': str(tmp_path / 'mount'),
            'fs_name': 'fs', 'mount_options': {},
        },
    }
    monkeypatch.setattr(helper, 'select_mount_port', lambda req: 10007)
    monkeypatch.setattr(helper, 'find_process', lambda req: None)

    class Stopped:
        def poll(self):
            return 1

    captured = []

    def launch(req, argv):
        import json
        state = json.loads((tmp_path / 'state' / 'state.json').read_text())
        captured.append((argv, state))
        return Stopped()

    monkeypatch.setattr(helper, '_launch', launch)
    with pytest.raises(ValueError, match='launcher failed'):
        helper.lifecycle(request)
    assert '--vfs_dummy_server_port=10007' in captured[0][0]
    assert captured[0][1]['vfs_dummy_server_port'] == 10007


def test_remount_reuses_owned_record_and_selects_new_port(tmp_path, monkeypatch):
    request = {
        'action': 'mount.remount', 'resource_id': 'resource', 'mds_addr': 'mds:6900',
        'record': {
            'state_dir': str(tmp_path / 'state'),
            'log_dir': str(tmp_path / 'logs'),
            'mount_path': str(tmp_path / 'mount'),
            'fs_name': 'fs', 'cache_group': 'group-a',
            'mount_options': {'vfs_dummy_server_port': '10007'},
        },
    }
    with helper.OwnedState(request['record']['state_dir'], 'resource:mount', create=True) as store:
        store.save({'state': 'unmounted', 'launch_started': True,
                    'vfs_dummy_server_port': 10007,
                    'process': {'pid': 999999, 'start_ticks': 'old'}})
    monkeypatch.setattr(helper, 'process_identity', lambda pid: None)
    monkeypatch.setattr(helper, 'mount_identity', lambda path: None)
    monkeypatch.setattr(helper, 'find_process', lambda req: None)
    monkeypatch.setattr(helper, 'select_mount_port', lambda req: 10008)

    class Stopped:
        def poll(self):
            return 1

    launched = []
    monkeypatch.setattr(helper, '_launch', lambda req, argv: launched.append(argv) or Stopped())
    with pytest.raises(ValueError, match='launcher failed'):
        helper.lifecycle(request)
    assert '--vfs_dummy_server_port=10008' in launched[0]
    assert '--cache_group=group-a' in launched[0]
    with helper.OwnedState(request['record']['state_dir'], 'resource:mount') as store:
        state = store.load()
    assert state['vfs_dummy_server_port'] == 10008
    assert state['launch_started'] is True


def test_mounted_remount_launches_hot_update_without_unmount(tmp_path, monkeypatch):
    request = {
        'action': 'mount.remount', 'resource_id': 'resource', 'mds_addr': 'mds:6900',
        'record': {
            'state_dir': str(tmp_path / 'state'), 'log_dir': str(tmp_path / 'logs'),
            'mount_path': str(tmp_path / 'mount'), 'fs_name': 'fs',
            'mount_options': {'vfs_dummy_server_port': '10007'},
        },
    }
    old = {'pid': 100, 'start_ticks': '1', 'exe': '/bin/dingo-client', 'argv': ['old']}
    new = {**old, 'pid': 101, 'start_ticks': '2'}
    mount = {'mount_id': '55', 'mount_path': request['record']['mount_path']}
    with helper.OwnedState(request['record']['state_dir'], 'resource:mount', create=True) as store:
        store.save({'state': 'mounted', 'process': old, 'mount': mount,
                    'vfs_dummy_server_port': 10007})
    monkeypatch.setattr(helper, 'process_identity', lambda pid: old if pid == 100 else new)
    monkeypatch.setattr(helper, 'mount_identity', lambda path: mount)
    monkeypatch.setattr(helper, 'find_process', lambda req, **kwargs: new)
    monkeypatch.setattr(helper, 'select_mount_port', lambda req: pytest.fail('hot update must reuse port'))
    launched = []
    class Running:
        def poll(self): return None
    monkeypatch.setattr(helper, '_launch', lambda req, argv: launched.append(argv) or Running())
    result = helper.lifecycle(request)
    assert result == ('mounted', {'mount_path': request['record']['mount_path'],
                                  'vfs_dummy_server_port': 10007, 'hot_updated': True})
    assert len(launched) == 1
    assert '--vfs_dummy_server_port=10007' in launched[0]
    with helper.OwnedState(request['record']['state_dir'], 'resource:mount') as store:
        assert store.load()['process'] == new
