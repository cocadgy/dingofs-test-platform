"""Real source/preflight submission; fake transport forbids remote workloads."""
import copy
import json

import pytest
from sqlalchemy import event, select

from test_functional_preflight import ready, invoke, deny_real_ssh
from dingofs_platform.functional.models import FunctionalRun, FunctionalPreflight, FunctionalModuleRun


def body(app, ready):
    preflight = invoke(app, ready)
    assert preflight.can_start
    return {**ready[0].model_dump(mode='json'), 'version': 2, 'idempotency_key': 'api-one',
            'preflight_token': preflight.token, 'confirmed_impacts': preflight.required_confirmations}


def test_v2_creation_freezes_binding_before_first_flush_and_consumes_token(admin, app, ready):
    payload = body(app, ready)
    response = admin.post('/api/v1/functional/runs', json=payload)
    assert response.status_code == 202, response.text
    value = response.json()
    assert value['version'] == 2 and value['can_manage'] is True
    assert value['children'][0]['env_name'] == 'env_ready'
    assert value['children'][0]['events'] == []
    assert value['children'][0]['result']['case_counts']['total'] == 1
    assert value['children'][0]['result']['case_counts']['completed'] == 0
    assert value['children'][0]['result']['report_status'] == 'pending'
    with app.state.session_factory() as db:
        row = db.get(FunctionalRun, value['id'])
        assert row.snapshot['runtime_binding']['immutable_path'] == '/opt/dtt/immutable-123/dtt'
        assert db.scalar(select(FunctionalPreflight)).consumed_by == row.id
    repeated = admin.post('/api/v1/functional/runs', json=payload)
    assert repeated.status_code == 202 and repeated.json()['id'] == value['id']
    payload['retries'] = 1
    assert admin.post('/api/v1/functional/runs', json=payload).status_code == 409


def test_missing_confirmation_does_not_create_run(admin, app, ready):
    payload = body(app, ready)
    payload['confirmed_impacts'] = []
    response = admin.post('/api/v1/functional/runs', json=payload)
    assert response.status_code == 409
    with app.state.session_factory() as db:
        assert db.scalar(select(FunctionalRun)) is None


def test_legacy_predefined_returns_real_preflight_and_v2_update_action(admin, app, ready):
    spec = ready[0]
    payload = dict(name='old', cluster_id=spec.cluster_id, env_name='env_ready',
                   selected={'quota': ['case.yaml']}, catalog_digest=spec.catalog_digest)
    response = admin.post('/api/v1/functional/runs', json=payload)
    assert response.status_code == 409, response.text
    assert response.json()['code'] == 'guided_submission_required'
    detail = response.json()['details']
    assert detail['preflight']['can_start']
    assert detail['preflight']['required_confirmations']
    assert detail['submission']['module_plans'][0]['module'] == 'quota'
    assert ready[2].calls
    with app.state.session_factory() as db:
        assert db.scalar(select(FunctionalRun)) is None


def test_child_history_uses_frozen_route_names_and_v2_legacy_routes_fail_actionably(admin, app, ready):
    value = admin.post('/api/v1/functional/runs', json=body(app, ready))
    assert value.status_code == 202, value.text
    run_id = value.json()['id']
    with app.state.session_factory.begin() as db:
        from dingofs_platform.inventory.models import Machine
        db.get(Machine, ready[3]['id']).name = 'renamed-later'
    child = admin.get('/api/v1/functional/runs/' + run_id).json()['children'][0]
    assert child['execution_targets'] == [{'machine_id': ready[3]['id'], 'name': 'node1',
                                          'ip': '192.0.2.1', 'user': 'test'}]
    assert admin.get('/api/v1/functional/runs').json()[0]['version'] == 2
    assert admin.post('/api/v1/functional/runs/' + run_id + '/rerun').status_code == 409
    assert admin.get('/api/v1/functional/runs/' + run_id + '/report/index.html').status_code == 409


@pytest.mark.parametrize('enabled', [True, False])
def test_real_queue_revalidation_blocks_drift_without_launch(admin, app, ready, enabled):
    value = admin.post('/api/v1/functional/runs', json=body(app, ready))
    assert value.status_code == 202, value.text
    run_id = value.json()['id']
    ready[2].fingerprint = 'd' * 64
    app.state.settings.functional_guided_enabled = enabled
    app.state.functional_manager.process(run_id)
    with app.state.session_factory() as db:
        child = db.scalar(select(FunctionalModuleRun).where(FunctionalModuleRun.run_id == run_id))
        assert child.launch_attempted_at is None
        assert db.get(FunctionalRun, run_id).state == 'failed'


@pytest.mark.parametrize('cancel', [False, True])
@pytest.mark.parametrize('dispatch', ['direct', 'monitor'])
def test_disabled_creation_gate_still_settles_queued_run(admin, app, ready, monkeypatch, cancel, dispatch):
    created = admin.post('/api/v1/functional/runs', json=body(app, ready))
    assert created.status_code == 202, created.text
    run_id = created.json()['id']
    if cancel:
        assert admin.post('/api/v1/functional/runs/' + run_id + '/stop').status_code == 200
    app.state.settings.functional_guided_enabled = False
    launches = []
    class Fake:
        def __init__(self, config): pass
        def start_child(self, payload): launches.append(payload['child_id'])
        def poll_child(self, payload, cursor, cancel=False):
            return {'missing': True, 'cursor_before': cursor}
    app.state.functional_transport = Fake
    manager = app.state.functional_manager
    if dispatch == 'direct':
        manager.process(run_id)
    else:
        from concurrent.futures import Future
        class ImmediatePool:
            def submit(self, function, *args):
                future = Future()
                future.set_result(function(*args))
                return future
        manager.pool = ImmediatePool()
        monkeypatch.setattr(manager.stop_event, 'wait', lambda timeout: manager.stop_event.set())
        manager.loop()
        manager.pool = None
    with app.state.session_factory() as db:
        row = db.get(FunctionalRun, run_id)
        assert row.state == ('cancelled' if cancel else 'unknown')
        child = db.scalar(select(FunctionalModuleRun).where(FunctionalModuleRun.run_id == run_id))
        assert (child.launch_attempted_at is None) is cancel
        assert (row.finished_at is not None) is cancel
    assert len(launches) == (0 if cancel else 1)


def test_stop_acquires_account_lock_before_parent_lock(admin, app, ready):
    created = admin.post('/api/v1/functional/runs', json=body(app, ready))
    assert created.status_code == 202, created.text
    statements = []
    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(app.state.engine, 'before_cursor_execute', capture)
    try:
        stopped = admin.post('/api/v1/functional/runs/' + created.json()['id'] + '/stop')
    finally:
        event.remove(app.state.engine, 'before_cursor_execute', capture)
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()['cancel_requested'] is True
    account = next(i for i, sql in enumerate(statements) if 'pg_advisory_xact_lock(7412082)' in sql)
    parent = next(i for i, sql in enumerate(statements) if 'functional_runs' in sql and 'FOR UPDATE' in sql)
    assert account < parent, 'Stop must match the scheduler account-before-parent lock order'


@pytest.mark.parametrize('mismatch', ['missing_parent', 'actor', 'digest', 'binding', 'owner', 'lease'])
def test_disabled_gate_admission_requires_exact_persisted_parent_and_leases(admin, app, ready, mismatch):
    from dingofs_platform.auth.models import User
    from dingofs_platform.errors import Problem
    from dingofs_platform.functional.preflight import revalidate_binding
    from dingofs_platform.functional.scheduler import lease_requests
    from dingofs_platform.functional.submission import NormalizedSubmission
    from dingofs_platform.operations.leases import ensure_leases
    created = admin.post('/api/v1/functional/runs', json=body(app, ready))
    assert created.status_code == 202, created.text
    run_id = created.json()['id']
    app.state.settings.functional_guided_enabled = False
    with app.state.session_factory.begin() as db:
        db.info['functional_settings'] = app.state.settings
        db.info['functional_preflight_transport'] = ready[2]
        parent = db.get(FunctionalRun, run_id)
        request = NormalizedSubmission.model_validate({key: value for key, value in parent.snapshot.items()
                                                       if key in NormalizedSubmission.model_fields})
        actor = db.scalar(select(User).where(User.username == ('member' if mismatch == 'actor' else 'admin')))
        binding = copy.deepcopy(parent.snapshot['runtime_binding'])
        owner = 'functional:' + run_id
        if mismatch != 'lease':
            assert ensure_leases(db, owner, lease_requests(parent)).acquired
        if mismatch == 'digest': request = request.model_copy(update={'request_digest': '0' * 64})
        if mismatch == 'binding': binding['immutable_path'] = '/opt/changed/dtt'
        if mismatch == 'owner': owner = 'functional:another-parent'
        with pytest.raises(Problem) as error:
            revalidate_binding(db, actor, request, binding, owner=owner,
                               admitted_run_id='missing' if mismatch == 'missing_parent' else run_id)
        assert error.value.code == 'preflight_changed'


def test_same_environment_children_freeze_exact_single_module_manifests(admin, app, ready, tmp_path):
    import hashlib
    from dingofs_platform.functional.catalog import catalogue
    from dingofs_platform.functional.schemas import RunSpec
    from dingofs_platform.functional.source_bridge import inspect_source
    from dingofs_platform.tool_packages.models import ToolJob
    from dingofs_platform.functional.scheduler import advance_parent
    spec, root, remote, control, profile = ready
    directory = root / 'testcases/client_test_cases'
    directory.mkdir()
    (directory / 'other.yaml').write_text('case_name: second\nsteps: []\n')
    manifest = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob('*') if p.is_file()}
    remote.runtime['source_manifest'] = manifest
    with app.state.session_factory.begin() as db:
        tool = db.scalar(select(ToolJob).where(ToolJob.action == 'install'))
        tool.result = {**tool.result, 'functional_runtime': copy.deepcopy(remote.runtime)}
    new = RunSpec(**{**spec.model_dump(), 'catalog_digest': catalogue(root / 'testcases')['digest'],
        'module_plans': [*spec.model_dump()['module_plans'], {'module': 'client', 'cases': ['other.yaml'],
                         'environment_profile_id': profile['id'], 'environment_profile_revision': profile['revision']}]})
    updated = (new, *ready[1:])
    created = admin.post('/api/v1/functional/runs', json=body(app, updated))
    assert created.status_code == 202, created.text
    children = created.json()['children']
    for child, module_dir in zip(children, ['quota_test_cases', 'client_test_cases']):
        descriptor = inspect_source(root, 'env_ready', {child['module']: [
            f'testcases/{module_dir}/{case}' for case in child['cases']]})
        assert child['environment_snapshot']['source_manifest'] == descriptor.source_manifest
    assert children[0]['environment_snapshot']['source_manifest'] != children[1]['environment_snapshot']['source_manifest']
    with app.state.session_factory.begin() as db:
        db.info['functional_settings'] = app.state.settings
        db.info['functional_preflight_transport'] = remote
        decision = advance_parent(db, created.json()['id'])
        assert decision.action == 'launch'
        assert decision.payload['context']['source_manifest'] == children[0]['environment_snapshot']['source_manifest']
        from dingofs_platform.operations.models import OperationLease
        keys = set(db.scalars(select(OperationLease.key).where(OperationLease.released_at.is_(None))))
        assert keys == {'machine:' + control['id'], 'runtime:' + control['id'], 'cluster:' + spec.cluster_id}
    # Validate the actual producer context loader, with only the separately
    # verified installed-package probe replaced. No setup/executor is invoked.
    import os, subprocess, sys
    code = '''
import json, pathlib, socket, subprocess, sys
sys.path.insert(0, sys.argv[1])
def denied(*args, **kwargs): raise AssertionError('external I/O forbidden')
socket.socket.connect = denied
subprocess.Popen = denied
from src.test_runner import runtime_context
payload = json.loads(pathlib.Path(sys.argv[3]).read_text())
runtime_context.verify_installed_runtime = lambda root: payload['context']['functional_runtime']
context = runtime_context.load_functional_context(sys.argv[3], payload['module'], payload['env_name'],
    payload['retries'], {'version': 1, 'modules': {payload['module']: payload['cases']},
    'hashes': {payload['module']: payload['hashes']}}, sys.argv[2], sys.argv[4])
assert dict(context.source_manifest) == payload['context']['source_manifest']
'''
    # Loader expects just the context file; keep payload separate for test args.
    code = code.replace("context = runtime_context.load_functional_context(sys.argv[3],",
        "context_path = pathlib.Path(sys.argv[4]).parent / 'context.json'\n"
        "context_path.write_text(json.dumps(payload['context']))\n"
        "context = runtime_context.load_functional_context(context_path,")
    from test_functional_scheduler import finished, ingest
    for position in range(2):
        child_dir = tmp_path / f'producer-{position}'
        child_dir.mkdir()
        payload_path = child_dir / 'payload.json'
        payload_path.write_text(json.dumps(decision.payload))
        outcome = subprocess.run([sys.executable, '-I', '-B', '-c', code,
            os.environ['FUNCTIONAL_CONTRACTS_TEST_ROOT'], str(root), str(payload_path), str(child_dir / 'output')],
            env={**os.environ, 'DTT_FUNCTIONAL_OUTPUT_DIR': str(child_dir / 'output')},
            capture_output=True, text=True, timeout=20)
        assert outcome.returncode == 0, outcome.stderr
        result = finished(decision)
        result['events'][-1]['data']['execution_targets'] = decision.payload['context']['resolved_targets']
        ingest(app, created.json()['id'], decision, result, child_dir)
        with app.state.session_factory.begin() as db:
            db.info['functional_settings'] = app.state.settings
            db.info['functional_preflight_transport'] = remote
            decision = advance_parent(db, created.json()['id'])
        assert decision.action == ('launch' if position == 0 else 'done')
