"""Module report API authorization, exact child isolation and private redaction."""
import base64
import copy
import hashlib
import os
from pathlib import Path
import shutil

import pytest
from sqlalchemy import select

from test_functional_preflight import ready, deny_real_ssh
from test_functional_guided_api import body
from dingofs_platform.functional.models import FunctionalModuleRun
from dingofs_platform.tool_packages.models import ToolJob


def report_run(admin, app, ready):
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


def test_module_report_api_redacts_and_checks_missing_source(admin, app, ready):
    run_id, child_id = report_run(admin, app, ready)
    calls = []
    def remote(config, code):
        calls.append((config, code))
        return {'data': base64.b64encode(b'<html>test-secret private-ak private-sk</html>').decode()}
    app.state.functional_report_transport = remote
    url = f'/api/v1/functional/runs/{run_id}/modules/{child_id}/report/index.html'
    response = admin.get(url)
    assert response.status_code == 200, response.text
    assert response.content == b'<html>[REDACTED] [REDACTED] [REDACTED]</html>'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert calls
    (ready[1] / 'conf/env/base.yaml').unlink()
    assert admin.get(url).status_code == 503
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
def test_historical_report_uses_private_archive_after_current_upgrade(admin, app, ready, tmp_path, damage):
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
        return {'data': base64.b64encode(b'<html>test-secret private-ak private-sk</html>').decode()}
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
        if damage is None:
            assert response.status_code == 200, response.text
            assert response.content == b'<html>[REDACTED] [REDACTED] [REDACTED]</html>'
        else:
            assert response.status_code == (403 if damage == 'unauthorized' else 503)
            assert not calls
    finally:
        for path in archive.rglob('*'):
            if path.is_dir() and not path.is_symlink(): path.chmod(0o700)
