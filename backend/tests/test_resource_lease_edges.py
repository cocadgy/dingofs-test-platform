"""Real API/worker regressions for preparation and retry lease boundaries."""
from types import SimpleNamespace
import json
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import select

from conftest import linked
from test_resource_api import begin, member, runner
from dingofs_platform.operations.leases import LeaseRequest, acquire_leases
from dingofs_platform.resources import execution
from dingofs_platform.operations.models import OperationLease
from dingofs_platform.clusters.transport import ClusterCommandResult, ExecutionIdentity, ClusterExecutionError
from dingofs_platform.resources.models import ResourceOperation


def plan_parameters(machine_id, action, source='tag'):
    binary = {'binary_source': source}
    if source == 'tag':
        binary.update(binary_tag='v5.2', binary_digest='sha256:' + 'a' * 64)
    else:
        binary['binary_directory'] = '/opt/dingo'
    if action == 'cache.plan':
        return {'group_name': 'lease-preparation', 'members': [{**member(machine_id, 21000), **binary}]}
    return {'fs_name': 'train', 'clients': [dict(machine_id=machine_id, target_user='test',
                                              mount_path='/mnt/train', **binary)]}


@pytest.mark.parametrize('action', ['cache.plan', 'mount.plan'])
@pytest.mark.parametrize('boundary', ['submission', 'execution'])
@pytest.mark.parametrize('key_type, mode', [('machine', 'exclusive'), ('runtime', 'exclusive'), ('runtime', 'shared')])
def test_tag_preparation_respects_leases(admin, app, runner, monkeypatch, action, boundary, key_type, mode):
    machine, cluster, _ = linked(admin)
    preparations = []
    def no_network(*args, **kwargs):
        preparations.append(True)
        raise ValueError('network preparation must not start under a conflicting lease')
    monkeypatch.setattr(execution.cache_images, 'ensure_cached', no_network)
    run = execution.run
    if boundary == 'execution':
        monkeypatch.setattr(execution, 'run', lambda *args: None)
        response = begin(admin, cluster, action, plan_parameters(machine['id'], action))
        assert response.status_code == 202, response.text
    with app.state.session_factory.begin() as db:
        assert acquire_leases(db, 'functional:other', [LeaseRequest(key_type + ':' + machine['id'], mode)]).acquired
    if boundary == 'submission':
        response = begin(admin, cluster, action, plan_parameters(machine['id'], action))
        assert response.status_code == 409, response.text
        assert response.json()['code'] == 'operation_conflict'
    else:
        run(SimpleNamespace(app=app, state=SimpleNamespace()), response.json()['id'])
        result = admin.get('/api/v1/resource-operations/' + response.json()['id']).json()
        assert result['state'] == 'failed'
        assert result['error_code'] == 'operation_conflict'
    assert not preparations
    assert not runner


@pytest.mark.parametrize('action', ['cache.plan', 'mount.plan'])
def test_path_only_plan_remains_readonly(admin, app, runner, action):
    machine, cluster, _ = linked(admin)
    with app.state.session_factory.begin() as db:
        acquire_leases(db, 'functional:other', [LeaseRequest('machine:' + machine['id'])])
    response = begin(admin, cluster, action, plan_parameters(machine['id'], action, 'path'))
    assert response.status_code == 202, response.text
    assert len(runner) == 1


def partial_create(admin, app, action):
    machine, cluster, _ = linked(admin)
    starts = []
    def transport(config, cmd, **kwargs):
        work = json.loads(cmd.resource_script)
        planning = work['action'].endswith('.plan')
        if not planning:
            starts.append(work)
        failure = not planning and len(starts) == 2
        data = {'effective_port': 21000, 'binary_info': {
            'path': '/opt/dingo-client', 'sha256': 'a' * 64, 'version': 'v5.2'}} if planning else {}
        return ClusterCommandResult(ExecutionIdentity('test', '/home/test', '/bin/dingo'),
            json.dumps({'state': 'failed' if failure else 'planned' if planning else
                        'running' if action == 'cache.create' else 'mounted',
                        'returncode': int(failure), 'data': data}), '', int(failure))
    app.state.resource_transport = transport
    if action == 'cache.create':
        parameters = {'group_name': 'partial-lease', 'members': [member(machine['id'], 21000 + i) for i in range(3)]}
    else:
        planned = begin(admin, cluster, 'mount.plan', {'fs_name': 'train', 'clients': [
            dict(machine_id=machine['id'], target_user='test', mount_path='/mnt/train', count=3)]})
        assert planned.status_code == 202, planned.text
        assert admin.get('/api/v1/resource-operations/' + planned.json()['id']).json()['state'] == 'succeeded'
        parameters = {'plan_id': planned.json()['id']}
    response = begin(admin, cluster, action, parameters)
    assert response.status_code == 202, response.text
    original = admin.get('/api/v1/resource-operations/' + response.json()['id']).json()
    assert original['state'] == 'failed' and original['error_code'] == 'query_failed', original
    assert len(starts) == 2
    return cluster, original, starts


@pytest.mark.parametrize('action', ['cache.create', 'mount.create'])
def test_retry_local_failure_preserves_original_retained_leases(admin, app, runner, monkeypatch, action):
    cluster, original, starts = partial_create(admin, app, action)
    owner = 'resource:' + original['id']
    with app.state.session_factory() as db:
        held = set(db.scalars(select(OperationLease.key).where(
            OperationLease.owner == owner, OperationLease.released_at.is_(None))))
    assert len(held) == 3
    def broken(*args):
        raise ValueError('unreadable saved credential')
    monkeypatch.setattr(execution, 'decrypt_password', broken)
    response = begin(admin, cluster, action, {'retry_operation_id': original['id']})
    assert response.status_code == 202, response.text
    result = admin.get('/api/v1/resource-operations/' + response.json()['id']).json()
    assert result['state'] == 'failed' and result['error_code'] == 'credential_unavailable'
    assert len(starts) == 2
    with app.state.session_factory() as db:
        assert set(db.scalars(select(OperationLease.key).where(
            OperationLease.owner == owner, OperationLease.released_at.is_(None)))) == held


@pytest.mark.parametrize('action', ['cache.create', 'mount.create'])
@pytest.mark.parametrize('boundary', ['submission', 'execution'])
def test_unknown_retry_cannot_be_bypassed_via_older_ancestor(admin, app, runner, action, boundary):
    cluster, original, starts = partial_create(admin, app, action)
    original_transport = app.state.resource_transport
    def lost_response(*args, **kwargs):
        raise ClusterExecutionError('timeout')
    app.state.resource_transport = lost_response
    retry = begin(admin, cluster, action, {'retry_operation_id': original['id']})
    assert retry.status_code == 202, retry.text
    result = admin.get('/api/v1/resource-operations/' + retry.json()['id']).json()
    assert result['state'] == 'failed' and result['error_code'] == 'timeout'
    app.state.resource_transport = original_transport
    if boundary == 'submission':
        response = begin(admin, cluster, action, {'retry_operation_id': original['id']})
        assert response.status_code == 409, response.text
        assert response.json()['code'] == 'retry_unverified'
    else:
        # A queued row admitted by an older worker must be checked again at
        # execution; its ancestor is valid but another descendant is unknown.
        with app.state.session_factory.begin() as db:
            previous = db.get(ResourceOperation, retry.json()['id'])
            values = {column.name: getattr(previous, column.name) for column in ResourceOperation.__table__.columns}
            oid = str(uuid4())
            values.update(id=oid, request_id=str(uuid4()), state='pending', result={'steps': []}, error_code=None)
            db.add(ResourceOperation(**values))
        execution.run(SimpleNamespace(app=app, state=SimpleNamespace()), oid)
        result = admin.get('/api/v1/resource-operations/' + oid).json()
        assert result['state'] == 'failed' and result['error_code'] == 'retry_unverified'
    assert len(starts) == 2
    with app.state.session_factory() as db:
        held = list(db.scalars(select(OperationLease).where(OperationLease.owner == 'resource:' + original['id'])))
        assert len(held) == 3 and all(row.released_at is None for row in held)


@pytest.mark.parametrize('action', ['cache.create', 'mount.create'])
def test_concurrent_retry_submission_has_only_one_generation(admin, app, runner, monkeypatch, action):
    cluster, original, starts = partial_create(admin, app, action)
    run = execution.run
    monkeypatch.setattr(execution, 'run', lambda *args: None)
    barrier = Barrier(2)
    def submit(_):
        barrier.wait(timeout=5)
        return begin(admin, cluster, action, {'retry_operation_id': original['id']})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit, range(2)))
    assert sorted(response.status_code for response in responses) == [202, 409]
    rejected = next(response for response in responses if response.status_code == 409)
    assert rejected.json()['code'] == 'retry_unverified'
    accepted = next(response for response in responses if response.status_code == 202)
    run(SimpleNamespace(app=app, state=SimpleNamespace()), accepted.json()['id'])
    result = admin.get('/api/v1/resource-operations/' + accepted.json()['id']).json()
    assert result['state'] == 'succeeded', result
    assert len(starts) == 4  # first success is not repeated by the winning retry
    with app.state.session_factory() as db:
        rows = list(db.scalars(select(OperationLease).where(OperationLease.owner == 'resource:' + original['id'])))
        assert len(rows) == 3 and all(row.released_at is not None for row in rows)
