"""Real PostgreSQL races and conservative evidence handling, without SSH."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import importlib
from threading import Barrier

import pytest
from sqlalchemy import select

from dingofs_platform.operations.models import OperationLease


@pytest.fixture
def leases():
    assert importlib.util.find_spec('dingofs_platform.operations.leases'), 'lease service is missing'
    return importlib.import_module('dingofs_platform.operations.leases')


def test_two_workers_only_one_acquires_same_targets(app, leases):
    barrier = Barrier(2)
    def acquire(owner):
        barrier.wait(timeout=5)
        with app.state.session_factory.begin() as db:
            return leases.acquire_leases(db, owner, [leases.LeaseRequest('machine:one'),
                leases.LeaseRequest('cluster:one')]).acquired
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(acquire, ['worker-one', 'worker-two']))
    assert sorted(results) == [False, True]
    with app.state.session_factory() as db:
        rows = list(db.scalars(select(OperationLease)))
        assert len(rows) == 2
        assert len({row.owner for row in rows}) == 1


def test_acquisition_is_all_or_none_and_transaction_owned(app, leases):
    with app.state.session_factory.begin() as db:
        leases.acquire_leases(db, 'first', [leases.LeaseRequest('machine:z')])
    with app.state.session_factory.begin() as db:
        decision = leases.acquire_leases(db, 'second', [leases.LeaseRequest('cluster:a'), leases.LeaseRequest('machine:z')])
        assert not decision.acquired
        assert decision.conflicts[0].owner == 'first'
        assert decision.conflicts[0].reason
    with app.state.session_factory() as db:
        assert not db.scalar(select(OperationLease).where(OperationLease.key == 'cluster:a'))
        assert leases.acquire_leases(db, 'rollback', [leases.LeaseRequest('machine:a')]).acquired
        db.rollback()
    with app.state.session_factory() as db:
        assert not db.scalar(select(OperationLease).where(OperationLease.owner == 'rollback'))


def test_shared_runtime_reentrant_owner_and_exclusive_upgrade(app, leases):
    with app.state.session_factory.begin() as db:
        for owner in ['run-one', 'run-two']:
            assert leases.acquire_leases(db, owner, [leases.LeaseRequest('runtime:control', 'shared')]).acquired
        assert leases.acquire_leases(db, 'run-one', [leases.LeaseRequest('runtime:control', 'shared')]).acquired
        assert not leases.acquire_leases(db, 'run-one', [leases.LeaseRequest('runtime:control')]).acquired
        assert not leases.acquire_leases(db, 'installer', [leases.LeaseRequest('runtime:control')]).acquired
        row = db.scalar(select(OperationLease).where(OperationLease.owner == 'run-one'))
        assert row.depth == 2


def test_unknown_and_retained_keep_leases(app, leases):
    with app.state.session_factory.begin() as db:
        leases.acquire_leases(db, 'unknown', [leases.LeaseRequest('cluster:one')])
        row = db.scalar(select(OperationLease))
        row.acquired_at = datetime.now(timezone.utc) - timedelta(days=365)
        row.heartbeat_at = row.acquired_at
    with app.state.session_factory.begin() as db:
        assert not leases.acquire_leases(db, 'new-worker', [leases.LeaseRequest('cluster:one')]).acquired
        evidence = leases.VerificationEvidence(owner='unknown', remote_ended=True, recovery_ok=True,
            verified_resources=frozenset({'cluster:one'}), remaining_resources=frozenset({'cluster:one'}),
            observed_at=datetime.now(timezone.utc))
        leases.release_verified(db, 'unknown', evidence)
    with app.state.session_factory() as db:
        assert leases.check_conflicts(db, [leases.LeaseRequest('cluster:one')])


@pytest.mark.parametrize('change', [dict(owner='other'), dict(remote_ended=False),
    dict(recovery_ok=False), dict(verified_resources=frozenset()),
    dict(observed_at=datetime(2000, 1, 1, tzinfo=timezone.utc))])
def test_incomplete_evidence_never_releases(app, leases, change):
    with app.state.session_factory.begin() as db:
        leases.acquire_leases(db, 'owner', [leases.LeaseRequest('cluster:one')])
        fields = dict(owner='owner', remote_ended=True, recovery_ok=True,
            verified_resources=frozenset({'cluster:one'}), remaining_resources=frozenset(),
            observed_at=datetime.now(timezone.utc))
        fields.update(change)
        leases.release_verified(db, 'owner', leases.VerificationEvidence(**fields))
        assert leases.check_conflicts(db, [leases.LeaseRequest('cluster:one')])


def test_verified_cleanup_can_release_exact_retained_owner(app, leases):
    with app.state.session_factory.begin() as db:
        leases.acquire_leases(db, 'owner', [leases.LeaseRequest('cluster:one'), leases.LeaseRequest('machine:one')])
        evidence = leases.VerificationEvidence(owner='owner', remote_ended=True, recovery_ok=True,
            verified_resources=frozenset({'machine:one'}), remaining_resources=frozenset(),
            observed_at=datetime.now(timezone.utc))
        leases.release_verified(db, 'owner', evidence)
        assert not leases.check_conflicts(db, [leases.LeaseRequest('machine:one')])
        assert leases.check_conflicts(db, [leases.LeaseRequest('cluster:one')])
        assert leases.acquire_leases(db, 'next', [leases.LeaseRequest('machine:one')]).acquired


def test_same_control_host_does_not_exclude_other_cluster_but_actual_targets_do(app, admin, leases):
    from conftest import machine
    control, target = machine(admin, 'control'), machine(admin, 'target')
    with app.state.session_factory.begin() as db:
        first = leases.functional_requests(db, 'cluster-one', control['id'], [{'targets': [
            {'host': 'target.test', 'mutates': True}]}])
        assert leases.acquire_leases(db, 'first', first).acquired
        other = leases.functional_requests(db, 'cluster-two', control['id'], [{'targets': []}])
        assert leases.acquire_leases(db, 'other', other).acquired
        same_host = leases.functional_requests(db, 'cluster-three', control['id'], [{'targets': [
            {'host': 'target.test', 'mutates': True}]}])
        assert not leases.acquire_leases(db, 'third', same_host).acquired
        assert not leases.acquire_leases(db, 'install', leases.tool_requests(control['id'], 'install')).acquired


def test_retained_cleanup_binds_exact_resource_and_keeps_shared_keys(app, admin, leases):
    from conftest import linked
    from dingofs_platform.functional.models import FunctionalRun, FunctionalModuleRun, FunctionalResource
    m, c, _ = linked(admin)
    with app.state.session_factory.begin() as db:
        parent = FunctionalRun(version=2, creator_id='actor', cluster_id=c['id'], machine_id=m['id'],
            name='retained', state='needs_attention', snapshot={}, finished_at=datetime.now(timezone.utc))
        db.add(parent); db.flush()
        child = FunctionalModuleRun(run_id=parent.id, module='client', position=0,
            state='retained', environment_snapshot={}, cases=[], case_hashes={}, finished_at=datetime.now(timezone.utc))
        db.add(child); db.flush()
        sibling = FunctionalModuleRun(run_id=parent.id, module='quota', position=1,
            state='retained', environment_snapshot={}, cases=[], case_hashes={}, finished_at=datetime.now(timezone.utc))
        db.add(sibling); db.flush()
        rows = [FunctionalResource(child_id=child.id if name == 'A' else sibling.id, resource_id=name, kind='mount', cluster=c['id'],
            host=m['address'], user='root', name=name, path='/tmp/' + name, port=None,
            owned=True, phase='retained', remote_identity={'mount_id': number}) for number, name in enumerate(['A', 'B'], 1)]
        db.add_all(rows); db.flush()
        owner = 'functional:' + parent.id
        requests = [leases.LeaseRequest('machine:' + m['id']), leases.LeaseRequest('cluster:' + c['id'])]
        leases.acquire_leases(db, owner, requests)
        evidence = leases.completion_evidence(owner, requests)
        target = dict(cluster=c['id'], host=m['address'], user='root', name='A', path='/tmp/A', port=None)
        sibling.state='running';db.flush()
        with pytest.raises(Exception) as error:
            leases.authorize_retained_cleanup(db, owner, evidence, child_id=child.id,
                resource_id='A', kind='mount', remote_identity={'mount_id':1}, target=target)
        assert getattr(error.value, 'code', '') == 'cleanup_not_verified'
        sibling.state='retained';db.flush()
        leases.authorize_retained_cleanup(db, owner, evidence, child_id=child.id,
            resource_id='A', kind='mount', remote_identity={'mount_id':1}, target=target)
        with pytest.raises(Exception) as error:
            leases.authorize_retained_cleanup(db, owner, evidence, child_id=sibling.id,
                resource_id='B', kind='mount', remote_identity={'mount_id':1}, target=target)
        assert getattr(error.value, 'code', '') == 'cleanup_not_verified'
        other_parent = FunctionalRun(version=2, creator_id='actor', cluster_id=c['id'], machine_id=m['id'],
            name='different', state='success', snapshot={}, finished_at=datetime.now(timezone.utc))
        db.add(other_parent); db.flush()
        foreign = FunctionalModuleRun(run_id=other_parent.id, module='client', position=0,
            state='retained', environment_snapshot={}, cases=[], case_hashes={}, finished_at=datetime.now(timezone.utc))
        db.add(foreign); db.flush()
        with pytest.raises(Exception) as error:
            leases.authorize_retained_cleanup(db, owner, evidence, child_id=foreign.id,
                resource_id='A', kind='mount', remote_identity={'mount_id':1}, target=target)
        assert getattr(error.value, 'code', '') == 'cleanup_not_verified'
        rows[0].phase = 'removed'; db.flush()
        leases.release_verified(db, owner, leases.completion_evidence(owner, requests))
        assert leases.check_conflicts(db, requests)
        rows[1].phase = 'removed'; db.flush()
        # Existing resources are verified in place, never deleted by the run.
        rows[0].phase='active';rows[0].owned=False;db.flush()
        sibling.state = 'running'; db.flush()
        leases.release_verified(db, owner, leases.completion_evidence(owner, requests))
        assert leases.check_conflicts(db, requests)
        sibling.state = 'success'; parent.state = 'running'; db.flush()
        leases.release_verified(db, owner, leases.completion_evidence(owner, requests))
        assert leases.check_conflicts(db, requests)
        parent.state = 'needs_attention'; db.flush()
        leases.release_verified(db, owner, leases.completion_evidence(owner, requests))
        assert not leases.check_conflicts(db, requests)
        rows[0].phase='retained';rows[0].owned=True;db.flush()
        with pytest.raises(Exception) as error:
            leases.authorize_retained_cleanup(db, owner, leases.completion_evidence(owner, requests), child_id=child.id,
                resource_id='A', kind='mount', remote_identity={'mount_id':1}, target=target)
        assert getattr(error.value, 'code', '') == 'cleanup_not_verified'


def test_readonly_tool_source_does_not_exclude_source_machine(app, leases):
    with app.state.session_factory.begin() as db:
        leases.acquire_leases(db, 'functional:source', [leases.LeaseRequest('machine:source'),
            leases.LeaseRequest('runtime:source', 'shared')])
        requests = leases.tool_requests('target', 'auto_install', {'tool':'dingo', 'source_machine_id':'source'})
        assert leases.acquire_leases(db, 'install:target', requests).acquired


@pytest.mark.parametrize('extra', ['status_host: other.test', 'host_override: other.test', 'chaos: {node: other.test}'])
def test_legacy_partial_host_scan_never_counts_as_complete(app, admin, leases, tmp_path, extra):
    from conftest import machine
    from dingofs_platform.errors import Problem
    m = machine(admin)
    root = tmp_path / 'testcases'; root.mkdir()
    env = tmp_path / 'conf' / 'env'; env.mkdir(parents=True)
    (env / 'test.yaml').write_text('env_test:\n  clients:\n    - host: node1.test\n  ' + extra + '\n')
    with app.state.session_factory() as db:
        with pytest.raises(Problem) as error:
            leases.legacy_functional_requests(db, 'cluster', m['id'], {'env_name':'env_test'}, root, strict=True)
        assert error.value.code == 'target_unresolved'
