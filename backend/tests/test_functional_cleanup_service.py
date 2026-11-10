"""Real ledger/lease cleanup authorization with a server-only live identity seam."""
import pytest
from sqlalchemy import select

from test_functional_preflight import ready, deny_real_ssh
from test_functional_retention_service import retained
from dingofs_platform.auth.models import User
from dingofs_platform.errors import Problem
from dingofs_platform.functional.models import FunctionalResource, FunctionalModuleRun
from dingofs_platform.inventory.models import Cluster
from dingofs_platform.operations.leases import LeaseRequest


def setup(admin, app, ready):
    run_id, keys = retained(admin, app, ready)
    with app.state.session_factory.begin() as db:
        row = db.scalar(select(FunctionalResource).where(FunctionalResource.resource_id == 'resource-0'))
        row.kind, row.name, row.path = 'filesystem', 'owned-fs', None
        row.remote_identity = {'fs_id': '77'}
    return run_id, keys


def live(monkeypatch):
    from dingofs_platform.functional import retention
    def probe(db, actor, parent, child, row):
        return {**retention.resource_request(row), 'status': 'present', 'identity': row.remote_identity,
                'namespace': 'mnt:[123]', 'process_namespace': 'mnt:[123]', 'boot_id': 'boot-123'}
    monkeypatch.setattr(retention, 'probe_resource', probe)


def resolve(app, ready, keys, name='owned-fs'):
    from dingofs_platform.functional.retention_cleanup import resolve_cleanup_exception
    with app.state.session_factory.begin() as db:
        actor = db.scalar(select(User).where(User.username == 'admin'))
        cluster = db.get(Cluster, ready[0].cluster_id)
        return resolve_cleanup_exception(db, actor, cluster, 'fs.delete', {'fs_name': name},
                                         [LeaseRequest(key) for key in keys])


def test_exact_retained_fs_allows_only_its_single_management_cleanup(admin, app, ready, monkeypatch):
    run_id, keys = setup(admin, app, ready)
    live(monkeypatch)
    context, steps = resolve(app, ready, keys)
    assert context['run_id'] == run_id and context['resource_id'] == 'resource-0'
    assert context['identity'] == {'fs_id': '77'}
    assert len(steps) == 1 and steps[0]['parameters'] == {'fs_name': 'owned-fs'}
    assert resolve(app, ready, keys, 'owned-fs-other') is None


def test_live_identity_replacement_and_missing_end_proof_block_exception(admin, app, ready, monkeypatch):
    from dingofs_platform.functional import retention
    run_id, keys = setup(admin, app, ready)
    monkeypatch.setattr(retention, 'probe_resource', lambda db, actor, parent, child, row:
        {**retention.resource_request(row), 'status': 'present', 'identity': {'fs_id': '88'}})
    assert resolve(app, ready, keys) is None
    live(monkeypatch)
    with app.state.session_factory.begin() as db:
        child = db.scalar(select(FunctionalModuleRun).where(FunctionalModuleRun.run_id == run_id))
        child.remote_identity = {}
    assert resolve(app, ready, keys) is None


def test_cleanup_context_cannot_be_reused_for_changed_planned_target(admin, app, ready, monkeypatch):
    from dingofs_platform.functional.retention_cleanup import revalidate_cleanup_exception
    run_id, keys = setup(admin, app, ready)
    live(monkeypatch)
    context, steps = resolve(app, ready, keys)
    steps[0]['parameters'] = {'fs_name': 'other'}
    with app.state.session_factory.begin() as db:
        actor = db.scalar(select(User).where(User.username == 'admin'))
        with pytest.raises(Problem) as exc:
            revalidate_cleanup_exception(db, actor, context, steps, [LeaseRequest(key) for key in keys])
        assert exc.value.code == 'cleanup_not_verified'


def test_uncertain_remote_identity_refuses_without_echoing_transport_error(admin, app, ready, monkeypatch):
    from dingofs_platform.functional import retention
    _, keys = setup(admin, app, ready)
    def unavailable(*args):
        raise RuntimeError('untrusted remote credentials must stay private')
    monkeypatch.setattr(retention, 'probe_resource', unavailable)
    assert resolve(app, ready, keys) is None
