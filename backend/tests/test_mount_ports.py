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
