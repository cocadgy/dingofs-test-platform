import io
import tarfile
import pytest
from dingofs_platform.resources import cache_binary, cache_images, remote_helper


def test_client_image_extract_does_not_pick_cache(tmp_path):
    archive, target = tmp_path / 'layer', tmp_path / 'client'
    with tarfile.open(archive, 'w') as tar:
        for name, data in [('dingofs/cache/sbin/dingo-cache', b'cache'), ('dingofs/client/sbin/dingo-client', b'client')]:
            member = tarfile.TarInfo(name); member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
    assert cache_images.extract_binary(archive, target, binary_path='dingofs/client/sbin/dingo-client') == 'found'
    assert target.read_bytes() == b'client'


def test_client_binary_path_uses_client_not_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_binary, 'inspect_cache_binary', lambda path, *args: {'path': str(path), 'sha256': 'a' * 64})
    info = cache_binary.prepare_cache_binary({'binary_source': 'path', 'binary_directory': str(tmp_path)}, component='dingo-client')
    assert info['path'] == str(tmp_path / 'dingo-client')


def test_pinned_mount_launch_bypasses_default_binary(monkeypatch):
    monkeypatch.setattr(remote_helper, 'verify_cache_binary', lambda info: info['path'])
    req = {'mds_addr': '127.0.0.1:6900', 'record': {'fs_name': 'test', 'mount_path': '/mnt/test', 'log_dir': '/tmp/log',
        'binary_info': {'path': '/opt/client/dingo-client'}, 'use_rdma': False}}
    args = remote_helper.mount_argv(req)
    assert args[0] == '/opt/client/dingo-client'
    assert '--fuse_mount_options=default_permissions,allow_other' in args
    assert '--allow_other' not in args


def test_explicit_source_requires_checked_binary():
    with pytest.raises(ValueError, match='检查'):
        remote_helper.mount_argv({'record': {'binary_source': 'tag'}})


def test_plan_directories_preserve_private_owned_state(tmp_path):
    root = tmp_path / 'dingofs-platform-resources-test' / 'resource'
    req = {'resource_id': 'resource', 'record': {'state_dir': str(root),
        'log_dir': str(root / 'logs'), 'mount_options': {}}}
    remote_helper.prepare_mount_directories(req)
    with remote_helper.OwnedState(str(root), 'resource:mount') as store:
        assert store.load() == {}


def test_unknown_startup_is_not_relaunched(tmp_path, monkeypatch):
    req = {'action': 'mount.create', 'resource_id': 'resource', 'mds_addr': 'm:6900',
           'record': {'state_dir': str(tmp_path / 'state'), 'mount_path': str(tmp_path / 'mnt')}}
    with remote_helper.OwnedState(req['record']['state_dir'], 'resource:mount', create=True) as store:
        store.save({'launch_started': True})
    monkeypatch.setattr(remote_helper, 'mounted', lambda p: False)
    monkeypatch.setattr(remote_helper, 'find_process', lambda r: None)
    monkeypatch.setattr(remote_helper, '_launch', lambda *a: pytest.fail('duplicate launch'))
    with pytest.raises(ValueError, match='启动状态'):
        remote_helper.lifecycle(req)


def test_mount_ports_reserve_and_pin(monkeypatch):
    monkeypatch.setattr(remote_helper, 'port_busy', lambda p: False)
    assert remote_helper.select_mount_port({'record': {'reserved_ports': [10000]}}) == 10001
    req = {'record': {'checked_port': 10001}}
    assert remote_helper.select_mount_port(req) == 10001
    monkeypatch.setattr(remote_helper, 'port_busy', lambda p: True)
    with pytest.raises(ValueError, match='端口'):
        remote_helper.select_mount_port(req)
