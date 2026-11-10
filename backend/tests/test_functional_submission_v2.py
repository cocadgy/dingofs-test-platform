"""Parent/child submission contract; only the dedicated PostgreSQL fixture is used."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from conftest import linked
from dingofs_platform.auth.models import User
from dingofs_platform.errors import Problem
from dingofs_platform.functional import schemas
from dingofs_platform.functional.models import FunctionalRun


def api():
    # A missing contract is an explicit RED assertion, not a collection error.
    assert hasattr(schemas, 'RunInputV2'), 'guided submission schema is missing'
    from dingofs_platform.functional.submission import normalize_submission, create_run
    return schemas.RunInputV2, normalize_submission, create_run


@pytest.fixture
def source():
    catalog = {'digest': 'a' * 64, 'modules': {
        'quota': [{'path': 'a.yaml', 'sha256': 'b' * 64}],
        'client': [{'path': 'b.yaml', 'sha256': 'c' * 64}],
    }}
    envs = {key: {'id': key, 'revision': 1, 'env_name': name,
                  'digest': digest * 64, 'source_manifest': {'conf/env/base.yaml': digest * 64},
                  'mds_addresses': ['10.0.0.1:6900'], 'targets': [],
                  'client_count': 1, 'cache_count': None, 'storage_type': 's3',
                  'programs': {}, 'directories': {}, 'modules': {}, 'issues': []}
            for key, name, digest in [('env1', 'env_original_one', 'd'), ('env2', 'env_original_two', 'e')]}
    body = {'version': 2, 'name': 'guided', 'cluster_id': 'cluster',
            'module_plans': [{'module': 'client', 'environment_profile_id': 'env2',
                              'environment_profile_revision': 1, 'cases': ['b.yaml']},
                             {'module': 'quota', 'environment_profile_id': 'env1',
                              'environment_profile_revision': 1, 'cases': ['a.yaml']}],
            'catalog_digest': 'a' * 64, 'idempotency_key': 'request-one',
            'preflight_token': 'server-issued-token', 'confirmed_impacts': []}
    return body, catalog, envs


@pytest.fixture
def ready(admin, app, source):
    _, cluster, _ = linked(admin)
    source[0]['cluster_id'] = cluster['id']
    return source


def normalize(source):
    schema, normalizer, _ = api()
    body, catalog, envs = source
    return normalizer(schema(**body), catalog, envs)


def persist(app, request, username='admin'):
    _, _, create = api()
    with app.state.session_factory.begin() as db:
        actor = db.scalar(select(User).where(User.username == username))
        return create(db, actor, request).id


def test_same_key_returns_same_parent_and_changed_body_conflicts(app, ready):
    request = normalize(ready)
    first = persist(app, request)
    assert persist(app, request) == first
    ready[0]['name'] = 'changed'
    with pytest.raises(Problem) as conflict:
        persist(app, normalize(ready))
    assert (conflict.value.status, conflict.value.code) == (409, 'idempotency_conflict')


def test_idempotent_replay_survives_later_machine_unavailability(app, ready):
    from dingofs_platform.inventory.models import Cluster, Machine
    request = normalize(ready)
    run_id = persist(app, request)
    with app.state.session_factory.begin() as db:
        cluster = db.get(Cluster, request.cluster_id)
        db.get(Machine, cluster.management_machine_id).maintenance = True
    assert persist(app, request) == run_id


def test_two_module_environments_are_distinct_snapshots(app, ready):
    request = normalize(ready)
    assert [plan.module for plan in request.module_plans] == ['quota', 'client']
    assert request.timeout_minutes == 1440
    assert request.retries == 0
    ready[2]['env1']['env_name'] = 'changed-after-normalization'
    run_id = persist(app, request)
    from dingofs_platform.functional.models import FunctionalModuleRun
    with app.state.session_factory() as db:
        parent = db.get(FunctionalRun, run_id)
        children = list(db.scalars(select(FunctionalModuleRun).where(
            FunctionalModuleRun.run_id == run_id).order_by(FunctionalModuleRun.position)))
        assert parent.deadline is None
        assert [(row.module, row.environment_snapshot['env_name'], row.environment_snapshot['digest'])
                for row in children] == [('quota', 'env_original_one', 'd' * 64),
                                         ('client', 'env_original_two', 'e' * 64)]
        assert all(row.deadline is None and row.started_at is None for row in children)
        assert children[0].case_hashes == {'a.yaml': 'b' * 64}


def test_legacy_single_env_normalized_but_history_readable(admin, app, ready):
    _, normalizer, _ = api()
    body, catalog, envs = ready
    legacy = schemas.RunInput(name='legacy', cluster_id=body['cluster_id'], env_name='env_original_one',
                              selected={'quota': ['a.yaml']}, catalog_digest=catalog['digest'])
    normalized = normalizer(legacy, catalog, envs)
    assert normalized.module_plans[0].environment_profile_id == 'env1'
    with app.state.session_factory.begin() as db:
        from dingofs_platform.inventory.models import Cluster
        actor = db.scalar(select(User).where(User.username == 'admin'))
        cluster = db.get(Cluster, body['cluster_id'])
        old = FunctionalRun(creator_id=actor.id, cluster_id=cluster.id, machine_id=cluster.management_machine_id,
                            name='old', state='success', snapshot={'env_name': 'env_original_one', 'selected': {'quota': ['a.yaml']}},
                            deadline=datetime(2020, 1, 1, tzinfo=timezone.utc))
        db.add(old); db.flush(); old_id = old.id
    result = admin.get('/api/v1/functional/runs/' + old_id)
    assert result.status_code == 200
    assert result.json()['snapshot']['env_name'] == 'env_original_one'


def test_digest_binds_environment_dependencies_and_cases_not_controls(source):
    original = normalize(source).request_digest
    source[0].update(idempotency_key='other', preflight_token='renewed', draft_id='draft', draft_revision=2,
                     confirmed_impacts=['f' * 64])
    assert normalize(source).request_digest == original
    source[2]['env1']['source_manifest']['conf/env/base.yaml'] = 'f' * 64
    assert normalize(source).request_digest != original
    source[2]['env1']['source_manifest']['conf/env/base.yaml'] = 'd' * 64
    source[1]['modules']['quota'][0]['sha256'] = 'f' * 64
    assert normalize(source).request_digest != original


@pytest.mark.parametrize('field,value', [('timeout_minutes', 0), ('timeout_minutes', 1441),
                                        ('retries', -1), ('retries', 6)])
def test_limits_are_rejected(source, field, value):
    schema, _, _ = api()
    source[0][field] = value
    with pytest.raises(ValidationError): schema(**source[0])


@pytest.mark.parametrize('mutation', ['duplicate', 'traversal', 'unknown', 'revision', 'catalog'])
def test_invalid_module_cases_and_stale_source_rejected(source, mutation):
    api()
    if mutation == 'duplicate': source[0]['module_plans'].append(copy.deepcopy(source[0]['module_plans'][0]))
    elif mutation == 'traversal': source[0]['module_plans'][0]['cases'] = ['../b.yaml']
    elif mutation == 'unknown': source[0]['module_plans'][0]['module'] = 'posix'
    elif mutation == 'revision': source[2]['env2']['revision'] = 2
    else: source[1]['digest'] = 'f' * 64
    with pytest.raises((ValidationError, Problem)): normalize(source)


def test_snapshots_do_not_copy_credentials_or_arbitrary_settings(app, ready):
    ready[2]['env1'].update(password='TOP-SECRET', settings={'s3_sk': 'TOP-SECRET'})
    run_id = persist(app, normalize(ready))
    with app.state.session_factory() as db:
        assert 'TOP-SECRET' not in str(db.get(FunctionalRun, run_id).snapshot)


def test_same_key_concurrent_transactions_create_once(app, ready):
    request = normalize(ready)
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: persist(app, request), range(2)))
    assert ids[0] == ids[1]
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(FunctionalRun)) == 1


def test_distinct_requests_can_queue_same_cluster(app, ready):
    first = persist(app, normalize(ready))
    ready[0]['idempotency_key'] = 'another'
    assert persist(app, normalize(ready)) != first


def test_legacy_active_uniqueness_survives_v2_queue(app, ready):
    from dingofs_platform.inventory.models import Cluster
    from sqlalchemy.exc import IntegrityError
    cluster_id = ready[0]['cluster_id']
    persist(app, normalize(ready))
    with app.state.session_factory() as db:
        machine_id = db.get(Cluster, cluster_id).management_machine_id

    def legacy_insert():
        try:
            with app.state.session_factory.begin() as db:
                actor = db.scalar(select(User).where(User.username == 'admin'))
                db.add(FunctionalRun(creator_id=actor.id, cluster_id=cluster_id, machine_id=machine_id,
                    name='legacy', snapshot={}, deadline=datetime.now(timezone.utc)))
            return 'created'
        except IntegrityError:
            return 'conflict'

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: legacy_insert(), range(2))) == ['conflict', 'created']


def test_submission_permission_is_enforced(app, ready):
    with pytest.raises(Problem) as denied: persist(app, normalize(ready), 'member')
    assert denied.value.status == 403


def test_v2_endpoint_is_closed_and_csrf_protected(admin, app, ready):
    api()
    response = admin.post('/api/v1/functional/runs', json=ready[0])
    assert response.status_code == 503
    app.state.settings.functional_guided_enabled = True
    assert admin.post('/api/v1/functional/runs', json=ready[0]).status_code == 503
    admin.headers.pop('X-CSRF-Token')
    assert admin.post('/api/v1/functional/runs', json=ready[0]).status_code == 403
    assert admin.get('/api/v1/functional/runs').json() == []


def test_legacy_manager_does_not_process_v2_parent(app, ready):
    run_id = persist(app, normalize(ready))
    app.state.functional_manager.process(run_id)
    with app.state.session_factory() as db:
        assert db.get(FunctionalRun, run_id).state == 'queued'


def test_frozen_snapshots_cannot_be_replaced(app, ready):
    from dingofs_platform.functional.models import FunctionalModuleRun
    run_id = persist(app, normalize(ready))
    with pytest.raises(ValueError, match='immutable'):
        with app.state.session_factory.begin() as db:
            db.get(FunctionalRun, run_id).snapshot = {'replacement': True}
    with pytest.raises(ValueError, match='immutable'):
        with app.state.session_factory.begin() as db:
            child = db.scalar(select(FunctionalModuleRun).where(FunctionalModuleRun.run_id == run_id))
            child.environment_snapshot = {'replacement': True}
    with pytest.raises(ValueError, match='immutable'):
        with app.state.session_factory.begin() as db:
            parent = db.get(FunctionalRun, run_id)
            parent.version = 1
            parent.snapshot = {'replacement': True}


def test_mutated_normalized_snapshot_is_rejected_before_persistence(app, ready):
    request = normalize(ready)
    request.environment_snapshots['quota']['env_name'] = 'mutated-after-preflight'
    with pytest.raises(Problem) as rejected:
        persist(app, request)
    assert (rejected.value.status, rejected.value.code) == (409, 'request_changed')


def test_nested_credential_fields_are_not_serialized(source):
    source[2]['env1']['programs']['password'] = 'NESTED-SECRET'
    with pytest.raises((ValidationError, Problem)): normalize(source)


def test_framework_descriptor_lists_and_impacts_round_trip(source):
    source[2]['env1'].update(
        programs={'dingo': '/opt/dingo', 'client_binaries': ['/opt/dingo-client']},
        directories={'mounts': ['/mnt/fixed']},
        modules={'quota': {'available': True, 'reasons': [], 'required_tools': ['python3'],
                           'impacts': ['changes quota'], 'fixed_resources': ['fixed-filesystem']}})
    frozen = normalize(source).environment_snapshots['quota']
    assert frozen['programs']['client_binaries'] == ['/opt/dingo-client']
    assert frozen['directories']['mounts'] == ['/mnt/fixed']
    assert frozen['modules']['quota']['impacts'] == ['changes quota']


def test_unique_children_events_and_reentrant_shared_lease_records(app, ready):
    from sqlalchemy.exc import IntegrityError
    from dingofs_platform.functional.models import FunctionalModuleRun, FunctionalEvent
    from dingofs_platform.operations.models import OperationLease
    run_id = persist(app, normalize(ready))
    with app.state.session_factory.begin() as db:
        child = db.scalar(select(FunctionalModuleRun).where(FunctionalModuleRun.run_id == run_id))
        child_id = child.id
        db.add(FunctionalEvent(child_id=child_id, seq=1, record={'version': 2}))
        for owner in ['one', 'two']:
            db.add(OperationLease(key='cluster/read', owner=owner, mode='shared', depth=2,
                                  acquired_at=datetime.now(timezone.utc)))
    with pytest.raises(IntegrityError):
        with app.state.session_factory.begin() as db:
            db.add(FunctionalEvent(child_id=child_id, seq=1, record={}))
    for module, position in [('quota', 5), ('fault', 0)]:
        with pytest.raises(IntegrityError):
            with app.state.session_factory.begin() as db:
                db.add(FunctionalModuleRun(run_id=run_id, module=module, position=position,
                    environment_snapshot={}, cases=[], case_hashes={}))


def test_migration_preserves_legacy_rows_and_allows_new_queue(app):
    """Run the complete chain in a disposable schema of the dedicated test DB."""
    from pathlib import Path
    from uuid import uuid4
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect, text
    from sqlalchemy.engine import make_url
    url = make_url(str(app.state.engine.url.render_as_string(hide_password=False)))
    assert url.host in ('127.0.0.1', 'localhost') and url.database.endswith('_test')
    cfg = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    from alembic.script import ScriptDirectory
    assert ScriptDirectory.from_config(cfg).get_current_head() == '7b1c9e4a602d', 'guided migration missing'
    schema = 'task7_migration_' + uuid4().hex
    with app.state.engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA {schema}'))
        connection.execute(text(f'SET LOCAL search_path TO {schema}'))
        cfg.attributes['connection'] = connection
        command.upgrade(cfg, '2f6d6db8c141')
        # No inventory references are required for this isolated legacy fixture.
        connection.execute(text('ALTER TABLE functional_runs DROP CONSTRAINT functional_runs_cluster_id_fkey'))
        connection.execute(text('ALTER TABLE functional_runs DROP CONSTRAINT functional_runs_machine_id_fkey'))
        connection.execute(text("""INSERT INTO functional_runs
            (id, created_at, updated_at, revision, creator_id, cluster_id, machine_id,
             name, state, phase, progress, snapshot, log, error, result, cancel_requested, deadline)
            VALUES ('legacy', now(), now(), 1, 'owner', 'cluster', 'machine', 'old', 'success',
                    'done', 100, '{"env_name":"env_original"}', '', '', '{}', false, '2020-01-01')"""))
        command.upgrade(cfg, 'head')
        row = connection.execute(text('SELECT version, snapshot, deadline FROM functional_runs WHERE id=\'legacy\'')).one()
        assert row.version == 1 and row.snapshot == {'env_name': 'env_original'}
        assert row.deadline.year == 2020
        assert 'uq_functional_active_cluster' not in {index['name'] for index in inspect(connection).get_indexes('functional_runs')}
        assert {'functional_module_runs', 'functional_preflights', 'functional_events',
                'functional_resources', 'operation_leases'} <= set(inspect(connection).get_table_names())
        command.downgrade(cfg, '2f6d6db8c141')
        assert connection.execute(text('SELECT snapshot FROM functional_runs WHERE id=\'legacy\'')).scalar() == {'env_name': 'env_original'}
        command.upgrade(cfg, 'head')
        for run_id in ['queued-one', 'queued-two']:
            connection.execute(text("""INSERT INTO functional_runs
                (id, created_at, updated_at, revision, creator_id, cluster_id, machine_id,
                 name, state, phase, progress, snapshot, log, error, result, cancel_requested, version)
                VALUES (:id, now(), now(), 1, 'owner', 'cluster', 'machine', 'guided', 'queued',
                        'waiting', 0, '{}', '', '', '{}', false, 2)"""), {'id': run_id})
        with pytest.raises(RuntimeError, match='Cannot downgrade'):
            with connection.begin_nested():
                command.downgrade(cfg, '2f6d6db8c141')
        assert connection.execute(text('SELECT count(*) FROM functional_runs WHERE version=2')).scalar() == 2
        # Explicitly remove only this test-created, random schema.
        connection.execute(text('SET LOCAL search_path TO public'))
        connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
