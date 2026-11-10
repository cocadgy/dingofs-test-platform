"""Exact residual identity checks never authorize broad lease-key cleanup."""
from copy import deepcopy
from types import SimpleNamespace

import pytest


def resource():
    return SimpleNamespace(child_id='child', resource_id='resource', kind='directory',
        cluster='mds:6900', host='node', user='test', name=None, path='/tmp/owned/exact', port=None,
        owned=True, phase='retained', remote_identity={'device_inode': '12:34'})


def observation(row, **overrides):
    value = {'child_id': row.child_id, 'resource_id': row.resource_id, 'kind': row.kind,
        'expected_identity': deepcopy(row.remote_identity),
        'target': {key: getattr(row, key) for key in ('cluster', 'host', 'user', 'name', 'path', 'port')},
        'status': 'absent', 'identity': None}
    value.update(overrides)
    return value


def test_absence_must_bind_full_exact_server_journal_identity():
    from dingofs_platform.functional.retention import checked_resource_phase
    row = resource()
    assert checked_resource_phase(row, observation(row)) == 'removed'
    for key, wrong in [('child_id', 'other'), ('resource_id', 'other'), ('kind', 'filesystem'),
        ('expected_identity', {'device_inode': '12:35'}), ('target', {'host': 'node'})]:
        assert checked_resource_phase(row, observation(row, **{key: wrong})) == 'unknown'


def test_same_name_replacement_and_missing_identity_are_never_verified():
    from dingofs_platform.functional.retention import checked_resource_phase
    row = resource()
    assert checked_resource_phase(row, observation(row, status='present', identity={'device_inode': '12:99'})) == 'unknown'
    row.remote_identity = {}
    assert checked_resource_phase(row, observation(row)) == 'unknown'


def test_owned_present_stays_retained_and_borrowed_exact_identity_stays_active():
    from dingofs_platform.functional.retention import checked_resource_phase
    row = resource()
    observed = observation(row, status='present', identity=row.remote_identity)
    assert checked_resource_phase(row, observed) == 'retained'
    row.owned = False
    assert checked_resource_phase(row, observed) == 'active'
    assert checked_resource_phase(row, observation(row)) == 'unknown'


@pytest.mark.parametrize('kind', ['client-upgrade', 'mds-membership', 'cache-flags', 'cache-weight'])
def test_special_recovery_cannot_be_verified_by_generic_absence(kind):
    from dingofs_platform.functional.retention import checked_resource_phase
    row = resource()
    row.kind = kind
    assert checked_resource_phase(row, observation(row)) == 'unknown'


def test_filesystem_relative_directory_requires_dependency_identity():
    from dingofs_platform.functional.retention import checked_resource_phase
    row = resource()
    row.remote_identity['filesystem_relative'] = {'fs_name': 'fs', 'fs_id': '12', 'relative_path': 'data'}
    assert checked_resource_phase(row, observation(row)) == 'unknown'


def test_stopped_cache_retains_registration_until_delete_is_verified():
    from dingofs_platform.functional.retention import checked_resource_phase
    row = resource()
    row.kind = 'cache'
    row.remote_identity = {'member_id': 'member', 'group_name': 'group', 'ip': '192.0.2.1',
                           'port': 12000, 'process': {'pid': 12, 'start': '34', 'exe': '/opt/dingo-cache'}}
    stopped = {**row.remote_identity, 'process': None}
    assert checked_resource_phase(row, observation(row, status='present', identity=stopped)) == 'retained'
    assert checked_resource_phase(row, observation(row, status='present', identity={**stopped, 'port': 12001})) == 'unknown'


def test_child_end_evidence_requires_exact_launch_pid_start_and_no_active_state():
    from dingofs_platform.functional.retention import child_ended
    child = SimpleNamespace(id='child', state='failed', launch_attempted_at=object(),
        remote_identity={'launch_token': 'token', 'remote_state': {'returncode': 1,
            'process': {'child_id': 'child', 'launch_token': 'token', 'pid': 12, 'start_time': '123', 'state': 'exited'},
            'end_proof': {'child_id': 'child', 'launch_token': 'token', 'pid': 12, 'start_time': '123', 'returncode': 1}}})
    assert child_ended(child)
    child.remote_identity['remote_state']['end_proof']['start_time'] = '124'
    assert not child_ended(child)
    child.state = 'not_run'
    child.launch_attempted_at = None
    child.remote_identity = {}
    assert child_ended(child)


@pytest.mark.parametrize('state,result,want', [
    ('pending', {}, False), ('running', {}, False), ('interrupted', {}, False),
    ('failed', {'steps': [{'remote_ended': True}]}, True),
    ('failed', {'steps': [{'remote_ended': False}]}, False),
    ('failed', {'zero_start': True}, True), ('succeeded', {}, True),
])
def test_cleanup_completion_uses_authoritative_end_not_just_terminal_status(state, result, want):
    from dingofs_platform.functional.retention import cleanup_operation_ended
    assert cleanup_operation_ended(SimpleNamespace(state=state, result=result)) is want
