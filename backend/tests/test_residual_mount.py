from copy import deepcopy
from types import SimpleNamespace

import pytest

from dingofs_platform.resources import external_mount as external


@pytest.fixture
def leftover(monkeypatch):
    mount = dict(mount_id='42', device='0:53', root='/', mount_path='/mnt/dead',
                 fs_type='fuse.dingofs', source='DingoFS:demo')
    host = SimpleNamespace(mount=deepcopy(mount), commands=[], rows=[dict(
        mount_path='/mnt/dead', kernel_mount=deepcopy(mount), cleanup_allowed=True)])
    monkeypatch.setattr(external.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(external.os, 'readlink', lambda p: 'mnt:[1]')
    monkeypatch.setattr(external.Path, 'read_text', lambda p: 'boot-test')
    def command(argv, **kwargs):
        host.commands.append(argv)
        host.mount = None
    host.helper = SimpleNamespace(mount_identity=lambda p: host.mount,
        scan_mounts=lambda m: {'mounts': host.rows}, run_command=command)
    host.req = dict(mds_addr='a:6900', record=dict(mount_path='/mnt/dead',
        kernel_mount=mount, namespace='mnt:[1]', boot_id='boot-test'))
    return host


def test_dead_mount_without_pid_is_detached_without_traversing_endpoint(leftover):
    assert external.unmount_discovered(leftover.req, leftover.helper)[0] == 'unmounted'
    assert leftover.commands == [['umount', '-i', '-l', '--no-canonicalize', '--', '/mnt/dead']]


@pytest.mark.parametrize('change', ['replacement', 'boot', 'namespace', 'live', 'stacked'])
def test_stale_or_ambiguous_scan_is_not_unmounted(leftover, change):
    if change == 'replacement': leftover.mount['mount_id'] = '99'
    if change == 'boot': leftover.req['record']['boot_id'] = 'other'
    if change == 'namespace': leftover.req['record']['namespace'] = 'other'
    if change == 'live': leftover.rows[0]['cleanup_allowed'] = False
    if change == 'stacked': leftover.rows.append(deepcopy(leftover.rows[0]))
    with pytest.raises(ValueError):
        external.unmount_discovered(leftover.req, leftover.helper)
    assert not leftover.commands


def test_already_unmounted_is_idempotent(leftover):
    leftover.mount = None
    assert external.unmount_discovered(leftover.req, leftover.helper)[1]['already_absent']
    assert not leftover.commands
