"""Authenticated complete report snapshots without source/redaction dependencies."""
import base64
import copy
import hashlib
import os
from pathlib import Path
import shutil
import io
import tarfile

import pytest
from sqlalchemy import select

from test_functional_preflight import ready, deny_real_ssh
from test_functional_guided_api import body
from dingofs_platform.functional.models import FunctionalModuleRun
from dingofs_platform.tool_packages.models import ToolJob


def report_run(admin, app, ready):
    object.__setattr__(app.state.settings, 'functional_report_cache_root', ready[1].parent / 'report-cache')
    relative = 'src/test_runner/functional_redaction.py'
    shutil.copyfile(Path(os.environ['FUNCTIONAL_CONTRACTS_TEST_ROOT']) / relative, ready[1] / relative)
    ready[2].runtime['source_manifest'][relative] = hashlib.sha256((ready[1] / relative).read_bytes()).hexdigest()
    with app.state.session_factory.begin() as db:
        tool = db.scalar(select(ToolJob).where(ToolJob.action == 'install'))
        tool.result = {**tool.result, 'functional_runtime': copy.deepcopy(ready[2].runtime)}
    response = admin.post('/api/v1/functional/runs', json=body(app, ready))
    assert response.status_code == 202, response.text
    run_id = response.json()['id']
    with app.state.session_factory.begin() as db:
        child = db.scalar(select(FunctionalModuleRun).where(FunctionalModuleRun.run_id == run_id))
        child_id = child.id
        child.result = {'report_status': 'ready', 'report_path': 'report/index.html'}
        child.remote_identity = {'root': '/home/test/.local/share/dingofs-platform/functional-v2/' + run_id + '/supervisor/' + child_id,
            'output': '/home/test/.local/share/dingofs-platform/functional-v2/' + run_id + '/output/' + run_id + '/' + child_id,
            'remote_state': {'verified_report': {'child_id': child_id, 'html_path': 'report/index.html'}}}
    return run_id, child_id


def bundle(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        for name, data in files.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
    return {'bundle': base64.b64encode(stream.getvalue()).decode()}


def test_module_report_preserves_bytes_and_reuses_snapshot_without_source(admin, app, ready):
    run_id, child_id = report_run(admin, app, ready)
    calls = []
    def remote(config, code):
        calls.append((config, code))
        return bundle({'index.html': b'<html>test-secret private-ak private-sk</html>', 'data/summary.json': b'{"total":3}'})
    app.state.functional_report_transport = remote
    url = f'/api/v1/functional/runs/{run_id}/modules/{child_id}/report/index.html'
    response = admin.get(url)
    assert response.status_code == 200, response.text
    assert response.content == b'<html>test-secret private-ak private-sk</html>'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert calls
    (ready[1] / 'conf/env/base.yaml').unlink()
    assert admin.get(url).content == response.content
    assert admin.get(url.replace('index.html', 'data/summary.json')).content == b'{"total":3}'
    assert response.headers['cache-control'] == 'private, no-cache'
    assert admin.get(url, headers={'If-None-Match': response.headers['etag']}).status_code == 304
    assert admin.get(url, headers={'If-None-Match': '"other", W/' + response.headers['etag']}).status_code == 304
    assert admin.get(url, headers={'If-None-Match': '*'}).status_code == 304
    assert len(calls) == 1


def test_report_missing_child_does_not_redirect_to_parent_or_latest(admin, app, ready):
    run_id, child_id = report_run(admin, app, ready)
    app.state.functional_report_transport = lambda *args: {'missing': True}
    url = f'/api/v1/functional/runs/{run_id}/modules/{child_id}/report/index.html'
    assert admin.get(url).status_code == 404
    assert admin.get(url.replace(child_id, 'other-child')).status_code == 404
    with app.state.session_factory.begin() as db:
        db.get(FunctionalModuleRun, child_id).result = {'report_status': 'missing'}
    assert admin.get(url).status_code == 404


@pytest.mark.parametrize('damage', [None, 'missing', 'changed', 'public', 'writable', 'symlink', 'cache', 'extra', 'unauthorized'])
def test_historical_report_does_not_require_source_archive(admin, app, ready, tmp_path, damage):
    import json
    from dingofs_platform.functional.models import FunctionalRun
    run_id, child_id = report_run(admin, app, ready)
    with app.state.session_factory() as db:
        manifest = db.get(FunctionalRun, run_id).snapshot['runtime_binding']['functional_runtime']['source_manifest']
    key = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    archive = tmp_path / 'archives'
    archive.mkdir(mode=0o700)
    entry = archive / key
    archived = entry / 'source'
    shutil.copytree(ready[1], archived)
    for path in sorted(entry.rglob('*'), reverse=True):
        path.chmod(0o500 if path.is_dir() else 0o400)
    entry.chmod(0o500)
    object.__setattr__(app.state.settings, 'functional_source_archive_root', archive)
    (ready[1] / 'conf/env/base.yaml').write_text('current version B has different credentials and code')
    calls = []
    def remote(*args):
        calls.append(True)
        return bundle({'index.html': b'<html>test-secret private-ak private-sk</html>'})
    app.state.functional_report_transport = remote
    target = archived / 'conf/storage.yaml'
    if damage == 'missing': entry.rename(archive / ('0' * 64))
    if damage in ('changed', 'writable'):
        target.chmod(0o600)
        if damage == 'changed':
            target.write_text('modified archive credential')
            target.chmod(0o400)
    if damage == 'public': target.chmod(0o444)
    if damage == 'symlink':
        target.parent.chmod(0o700)
        target.unlink()
        target.symlink_to(ready[1] / 'conf/storage.yaml')
        target.parent.chmod(0o500)
    if damage in ('cache', 'extra'):
        archived.chmod(0o700)
        extra = archived / ('injected.pyc' if damage == 'cache' else 'extra.py')
        extra.write_bytes(b'not pinned')
        extra.chmod(0o400)
        archived.chmod(0o500)
    if damage == 'unauthorized':
        assert admin.post('/api/v1/auth/login', json={
            'username': 'member', 'password': 'test-password-123'}).status_code == 200
    url = f'/api/v1/functional/runs/{run_id}/modules/{child_id}/report/index.html'
    try:
        response = admin.get(url)
        if damage != 'unauthorized':
            assert response.status_code == 200, response.text
            assert response.content == b'<html>test-secret private-ak private-sk</html>'
        else:
            assert response.status_code == 403
            assert not calls
    finally:
        for path in archive.rglob('*'):
            if path.is_dir() and not path.is_symlink(): path.chmod(0o700)


@pytest.mark.parametrize('damage,status', [('user', 403), ('machine_owner', 403), ('connection', 409), ('archived', 503), ('verified', 404)])
def test_warm_cache_authorizes_before_conditional_response(admin, app, ready, damage, status):
    from dingofs_platform.functional.models import FunctionalRun
    from dingofs_platform.inventory.models import Machine
    from dingofs_platform.auth.models import User
    run_id, child_id = report_run(admin, app, ready)
    app.state.functional_report_transport = lambda *args: bundle({'index.html': b'private'})
    url = f'/api/v1/functional/runs/{run_id}/modules/{child_id}/report/index.html'
    first = admin.get(url)
    assert first.status_code == 200
    if damage in ('user', 'machine_owner'):
        if damage == 'machine_owner':
            with app.state.session_factory.begin() as db:
                owner = db.scalar(select(User).where(User.username == 'admin'))
                owner.role = 'member'
                db.get(Machine, ready[3]['id']).creator_id = None
        else:
            assert admin.post('/api/v1/auth/login', json={'username': 'member', 'password': 'test-password-123'}).status_code == 200
    else:
        with app.state.session_factory.begin() as db:
            machine = db.get(Machine, ready[3]['id'])
            if damage == 'connection': machine.address = '192.0.2.2'
            if damage == 'archived': machine.archived = True
            if damage == 'verified': db.get(FunctionalModuleRun, child_id).remote_identity = {}
    assert admin.get(url, headers={'If-None-Match': first.headers['etag']}).status_code == status


def test_prefetch_populates_snapshot_for_offline_access(admin, app, ready):
    from dingofs_platform.functional.reports import prefetch_report
    run_id, child_id = report_run(admin, app, ready)
    with app.state.session_factory() as db:
        db.info.update(functional_settings=app.state.settings,
                       functional_report_transport=lambda *args: bundle({'index.html': b'prefetched'}))
        prefetch_report(db, run_id, child_id)
    def offline(*args):
        raise RuntimeError('offline')
    app.state.functional_report_transport = offline
    assert admin.get(f'/api/v1/functional/runs/{run_id}/modules/{child_id}/report/index.html').content == b'prefetched'


def test_manager_prefetch_runs_after_commit_and_failure_keeps_result(admin, app, ready, monkeypatch):
    from types import SimpleNamespace
    from dingofs_platform.functional.manager import FunctionalManager
    run_id, child_id = report_run(admin, app, ready)
    monkeypatch.setattr('dingofs_platform.functional.scheduler.advance_parent',
                        lambda *args: SimpleNamespace(action='poll', child_id=child_id, payload={}, cursor={}, cancel=False))
    class Transport:
        def __init__(self, config): pass
        def poll_child(self, *args): return {}
    app.state.functional_transport = Transport
    def observe(db, run_id, child_id, observation):
        db.get(FunctionalModuleRun, child_id).state = 'success'
    monkeypatch.setattr('dingofs_platform.functional.scheduler.record_observation', observe)
    seen = []
    def prefetch(db, parent, child):
        with app.state.session_factory() as other:
            seen.append(other.get(FunctionalModuleRun, child).state)
        raise RuntimeError('cache unavailable')
    monkeypatch.setattr('dingofs_platform.functional.reports.prefetch_report', prefetch)
    FunctionalManager(app).process_guided(run_id)
    assert seen == ['success']
    with app.state.session_factory() as db:
        assert db.get(FunctionalModuleRun, child_id).state == 'success'
