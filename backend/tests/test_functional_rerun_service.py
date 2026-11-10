"""Real DB/preflight reruns using synthetic source and strictly read-only fake SSH."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from test_functional_preflight import ready, deny_real_ssh
from test_functional_guided_api import body
from dingofs_platform.auth.models import User
from dingofs_platform.errors import Problem
from dingofs_platform.functional.models import FunctionalRun, FunctionalModuleRun, FunctionalPreflight


def original(admin, app, ready):
    response = admin.post('/api/v1/functional/runs', json=body(app, ready))
    assert response.status_code == 202, response.text
    run_id = response.json()['id']
    with app.state.session_factory.begin() as db:
        row = db.get(FunctionalRun, run_id)
        row.state, row.finished_at = 'failed', datetime.now(timezone.utc)
        child = db.scalar(select(FunctionalModuleRun).where(FunctionalModuleRun.run_id == run_id))
        child.state, child.finished_at = 'failed', row.finished_at
        child.launch_attempted_at = row.finished_at
        process = dict(state='exited', child_id=child.id, launch_token='rerun-token', pid=12, start_time='123')
        child.remote_identity = {'launch_token': 'rerun-token', 'remote_state': {'process': process, 'returncode': 1,
            'end_proof': {**{k: v for k, v in process.items() if k != 'state'}, 'returncode': 1}}}
        child.result = {'end_proof': True, 'cleanup_status': 'cleaned', 'recovery_status': 'not_required',
            'retained_resources': [], 'failed_cases': ['case.yaml'], 'missing': [], 'not_run': [],
            'case_results': [{'case_path': 'case.yaml', 'status': 'FAIL'}]}
    return run_id


def rerun(app, run_id, key='rerun-key'):
    from dingofs_platform.functional.reruns import rerun_parent
    with app.state.session_factory.begin() as db:
        db.info['functional_settings'] = app.state.settings
        db.info['functional_preflight_transport'] = app.state.functional_preflight_transport
        actor = db.scalar(select(User).where(User.username == 'admin'))
        return rerun_parent(db, actor, run_id, True, key).id


def test_rerun_consumes_fresh_preflight_and_returns_same_parent_for_retry(admin, app, ready):
    old = original(admin, app, ready)
    ready[2].calls.clear()
    new = rerun(app, old)
    assert new != old and ready[2].calls
    assert rerun(app, old) == new
    with app.state.session_factory() as db:
        assert db.get(FunctionalRun, new).snapshot['rerun_of'] == old
        assert len(list(db.scalars(select(FunctionalPreflight).where(FunctionalPreflight.consumed_by == new)))) == 1
        child = db.scalar(select(FunctionalModuleRun).where(FunctionalModuleRun.run_id == new))
        assert child.cases == ['case.yaml'] and not child.remote_identity and child.state == 'queued'


def test_rerun_refuses_source_drift_and_missing_original_confirmation(admin, app, ready):
    old = original(admin, app, ready)
    with app.state.session_factory.begin() as db:
        token = db.scalar(select(FunctionalPreflight).where(FunctionalPreflight.consumed_by == old))
        token.required_confirmations = []
    with pytest.raises(Problem) as exc:
        rerun(app, old)
    assert exc.value.code == 'rerun_confirmation_required'
    path = ready[1] / 'conf/env/base.yaml'
    path.write_text(path.read_text() + '\n# source changed\n')
    with pytest.raises(Problem) as exc:
        rerun(app, old, 'different')
    assert exc.value.status == 409
    with app.state.session_factory() as db:
        assert len(list(db.scalars(select(FunctionalRun)))) == 1


def test_rerun_revalidates_runtime_inventory_and_lease_occupancy(admin, app, ready):
    from dingofs_platform.operations.leases import acquire_leases, LeaseRequest
    old = original(admin, app, ready)
    with app.state.session_factory.begin() as db:
        acquire_leases(db, 'resource:occupied', [LeaseRequest('machine:' + ready[3]['id'])])
    with pytest.raises(Problem):
        rerun(app, old)
    with app.state.session_factory() as db:
        assert len(list(db.scalars(select(FunctionalRun)))) == 1


def test_rerun_rejects_acknowledgement_bound_to_different_request(admin, app, ready):
    old = original(admin, app, ready)
    with app.state.session_factory.begin() as db:
        token = db.scalar(select(FunctionalPreflight).where(FunctionalPreflight.consumed_by == old))
        token.request_digest = 'f' * 64
    with pytest.raises(Problem) as exc:
        rerun(app, old)
    assert exc.value.code == 'rerun_confirmation_required'
