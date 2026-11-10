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
