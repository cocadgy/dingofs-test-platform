"""Real HTTP/preflight/source/DB/worker/events/reports; only remote I/O is fake.

No live SSH or workload is permitted. Tests use TEST_DATABASE_URL exclusively.
"""
import ast
import base64
import copy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from test_functional_preflight import ready, deny_real_ssh
from test_functional_scheduler import finished
from dingofs_platform.functional.event_reader import read_events
from dingofs_platform.functional.manager import FunctionalManager
from dingofs_platform.functional.models import FunctionalRun, FunctionalModuleRun
from dingofs_platform.operations.models import OperationLease
from dingofs_platform.tool_packages.models import ToolJob


@pytest.fixture(autouse=True)
def isolated(app, monkeypatch):
    url = app.state.engine.url
    assert url.database.endswith('_test') and url.host in ('127.0.0.1', 'localhost')
    from dingofs_platform.functional.transport import Transport
    def denied(*args, **kwargs):
        raise AssertionError('unmocked remote network/SSH is forbidden')
    monkeypatch.setattr(Transport, 'call', denied)
    import socket
    original = socket.socket.connect
    def connect(sock, address):
        if (isinstance(address, tuple) and
                (address[0] not in ('127.0.0.1', 'localhost') or address[1] != (url.port or 5432))):
            denied()
        return original(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', connect)


@pytest.fixture
def two_environments(admin, app, ready):
    spec, root, remote, control, _ = ready
    (root / 'conf/env/second.yaml').write_text('env_second:\n  base: template\n')
    (root / 'testcases/client_test_cases').mkdir()
    (root / 'testcases/client_test_cases/second.yaml').write_text('case_name: second\nsteps: []\n')
    relative = 'src/test_runner/functional_redaction.py'
    shutil.copyfile(Path(os.environ['FUNCTIONAL_CONTRACTS_TEST_ROOT']) / relative, root / relative)
    remote.runtime['source_manifest'] = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                       for p in root.rglob('*') if p.is_file()}
    with app.state.session_factory.begin() as db:
        tool = db.scalar(select(ToolJob).where(ToolJob.action == 'install'))
        tool.result = {**tool.result, 'functional_runtime': copy.deepcopy(remote.runtime)}
    assert admin.post('/api/v1/functional/environments/sync-predefined').status_code == 200
    profiles = {p['name']: p for p in admin.get('/api/v1/functional/environments').json()}
    catalog = admin.get('/api/v1/functional/options').json()
    payload = {**spec.model_dump(mode='json'), 'catalog_digest': catalog['digest'], 'module_plans': []}
    for module, case, name in [('quota', 'case.yaml', 'env_ready'), ('client', 'second.yaml', 'env_second')]:
        profile = profiles[name]
        payload['module_plans'].append(dict(module=module, cases=[case], environment_profile_id=profile['id'],
                                          environment_profile_revision=profile['revision']))
    return payload, root, remote


def submit(admin, payload):
    checked = admin.post('/api/v1/functional/preflight', json=payload)
    assert checked.status_code == 200, checked.text
    preflight = checked.json()
    assert preflight['can_start'], preflight
    created = admin.post('/api/v1/functional/runs', json={**payload, 'version': 2,
        'idempotency_key': 'whole-flow', 'preflight_token': preflight['token'],
        'confirmed_impacts': preflight['required_confirmations']})
    assert created.status_code == 202, created.text
    return created.json()


def remote_transport(app, tmp_path, *, retained=False, lost=False):
    launches = []
    class Remote:
        def __init__(self, config):
            assert config.host == '192.0.2.1' and config.username == 'test'
        def start_child(self, payload):
            assert payload['module'] in ('quota', 'client') and len(payload['cases']) == 1
            launches.append(copy.deepcopy(payload))
        def poll_child(self, payload, cursor, cancel=False):
            if lost:
                return {'missing': True, 'cursor_before': cursor}
            value = finished(SimpleNamespace(payload=payload), failed=retained,
                             cleanup='retained' if retained else 'cleaned')
            events = value.pop('events')
            events[-1]['data']['execution_targets'] = payload['context']['resolved_targets']
            if retained:
                resource = dict(id='owned-dir', kind='directory', cluster='node1.test:6900',
                    host='node1.test', user='test', name=None, path='/tmp/owned/child-exact', port=None,
                    owned=True, phase='retained', remote_identity={'device_inode': '12:34'})
                events[-1]['data']['retained_resources'] = [resource]
            path = tmp_path / payload['child_id']
            path.write_text(''.join(json.dumps(row) + '\n' for row in events))
            base = '/home/test/.local/share/dingofs-platform/functional-v2/' + payload['parent_id']
            return {**value, 'cursor_before': cursor, 'event_batch': asdict(read_events(path, 0)),
                'has_more': False, 'verified_report': {'child_id': payload['child_id'], 'html_path': 'report/index.html'},
                'root': base + '/supervisor/' + payload['child_id'],
                'output': base + '/output/' + payload['parent_id'] + '/' + payload['child_id']}
    app.state.functional_transport = Remote
    return launches


def test_two_environments_submit_two_single_module_children_and_isolated_reports(admin, app, two_environments, tmp_path):
    row = submit(admin, two_environments[0])
    assert [c['env_name'] for c in row['children']] == ['env_ready', 'env_second']
    launches = remote_transport(app, tmp_path)
    for _ in range(3):
        app.state.functional_manager.process(row['id'])
    detail = admin.get('/api/v1/functional/runs/' + row['id']).json()
    assert detail['state'] == 'success', detail
    assert [payload['module'] for payload in launches] == ['quota', 'client']
    assert [payload['env_name'] for payload in launches] == ['env_ready', 'env_second']
    assert all(len(c['events']) == 3 and c['result']['case_counts']['passed'] == 1 for c in detail['children'])
    def report(config, code):
        child = next(c for c in detail['children'] if c['id'] in code)
        return {'data': base64.b64encode(f"<html>{child['module']} test-secret private-ak</html>".encode()).decode()}
    app.state.functional_report_transport = report
    for child in detail['children']:
        response = admin.get(f"/api/v1/functional/runs/{row['id']}/modules/{child['id']}/report/index.html")
        assert response.status_code == 200, response.text
        assert response.text == f"<html>{child['module']} [REDACTED] [REDACTED]</html>"
    with app.state.session_factory() as db:
        assert db.query(ToolJob).count() == 1, 'preflight/submission must not install tools'
        assert not list(db.scalars(select(OperationLease).where(OperationLease.released_at.is_(None))))


def test_retained_first_failure_never_launches_second_then_exact_readonly_verification_releases(admin, app, two_environments, tmp_path):
    row = submit(admin, two_environments[0])
    launches = remote_transport(app, tmp_path, retained=True)
    for _ in range(3):
        app.state.functional_manager.process(row['id'])
    detail = admin.get('/api/v1/functional/runs/' + row['id']).json()
    assert len(launches) == 1
    assert detail['children'][1]['state'] == 'not_run'
    assert detail['children'][0]['result']['retained_resources'][0]['id'] == 'owned-dir'
    present = True
    def probe(config, code):
        request = ast.literal_eval(code.splitlines()[0].removeprefix('REQUEST='))
        assert request['target']['path'] == '/tmp/owned/child-exact'
        return {**{key: request[key] for key in ('child_id', 'resource_id', 'kind', 'expected_identity', 'target')},
            'status': 'present' if present else 'absent',
            'identity': request['expected_identity'] if present else None}
    app.state.functional_retention_transport = probe
    endpoint = f"/api/v1/functional/runs/{row['id']}/resources/verify"
    first = admin.post(endpoint)
    assert first.status_code == 200, first.text
    assert first.json()['remaining_resources']
    present = False
    second = admin.post(endpoint)
    assert second.status_code == 200, second.text
    assert second.json()['remaining_resources'] == []
    with app.state.session_factory() as db:
        assert all(lease.released_at is not None for lease in db.scalars(select(OperationLease)))


def test_unknown_restart_with_creation_disabled_polls_without_duplicate_launch(admin, app, two_environments, tmp_path):
    row = submit(admin, two_environments[0])
    launches = remote_transport(app, tmp_path, lost=True)
    app.state.functional_manager.process(row['id'])
    app.state.settings.functional_guided_enabled = False
    restarted = FunctionalManager(app)
    for _ in range(3):
        restarted.process(row['id'])
    assert len(launches) == 1
    detail = admin.get('/api/v1/functional/runs/' + row['id']).json()
    assert detail['state'] == 'unknown'
    assert detail['children'][1]['state'] == 'queued'
    with app.state.session_factory() as db:
        assert db.get(FunctionalModuleRun, detail['children'][1]['id']).launch_attempted_at is None
        assert list(db.scalars(select(OperationLease).where(OperationLease.released_at.is_(None))))
