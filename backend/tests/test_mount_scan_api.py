import json
import shlex
from uuid import uuid4

import pytest
from sqlalchemy import select

from conftest import linked, machine
from dingofs_platform.clusters.transport import ClusterCommandResult, ExecutionIdentity, ClusterExecutionError
from dingofs_platform.inventory.models import Machine, Cluster
from dingofs_platform.resources import commands
from dingofs_platform.resources.models import ManagedResource


def begin(admin, cluster, ids):
    return admin.post(f'/api/v1/clusters/{cluster["id"]}/resource-operations', json={
        "action": "mount.scan", "parameters": {"machine_ids": ids},
        "request_id": str(uuid4()), "base_revision": cluster["revision"],
    })


@pytest.mark.parametrize("failure", [False, "transport", "credential"])
def test_scan_keeps_each_machine_result_without_creating_resources(admin, app, failure):
    m, c, _ = linked(admin)
    m2 = machine(admin, "scan2")
    with app.state.session_factory.begin() as db:
        db.get(Machine, m2["id"]).ssh_password_ciphertext = db.get(Machine, m["id"]).ssh_password_ciphertext
        if failure == "credential":
            db.get(Machine, m["id"]).ssh_password_ciphertext = "invalid-ciphertext"
    calls = []
    def transport(config, cmd, **kw):
        req = json.loads(shlex.split(cmd.resource_script)[-1])
        calls.append(req)
        assert cmd.target_user == "root" and not cmd.resource_requires_dingo
        assert req["action"] == "mount.scan" and not req["commands"]
        if failure == "transport" and len(calls) == 1:
            raise ClusterExecutionError("connect_failed")
        return ClusterCommandResult(ExecutionIdentity("root", "/root", ""), json.dumps({
            "state": "succeeded", "data": {"mounts": [], "scanned_at": "now"}, "returncode": 0,
        }), "", 0)
    app.state.resource_transport = transport
    response = begin(admin, c, [m["id"], m2["id"]])
    assert response.status_code == 202, response.text
    op = admin.get('/api/v1/resource-operations/' + response.json()["id"]).json()
    assert op["state"] == ("failed" if failure else "succeeded"), op
    assert len(calls) == (1 if failure == "credential" else 2)
    steps = op["result"]["steps"]
    assert [s["machine_id"] for s in steps] == [m["id"], m2["id"]]
    assert steps[0]["failed"] == bool(failure) and not steps[1]["failed"]
    with app.state.session_factory() as db:
        assert list(db.scalars(select(ManagedResource))) == []


def test_scan_rejects_missing_credentials_before_any_remote_work(admin, app):
    _, c, _ = linked(admin)
    m = machine(admin, "no-password")
    app.state.resource_transport = lambda *a, **k: pytest.fail("unauthorized SSH")
    response = begin(admin, c, [m["id"]])
    assert response.status_code == 422 and response.json()["code"] == "ssh_password_missing"


def test_scan_checks_machine_and_cluster_ownership(admin, app):
    m, c, _ = linked(admin)
    admin.post('/api/v1/auth/logout')
    login = admin.post('/api/v1/auth/login', json={"username": "member", "password": "test-password-123"})
    admin.headers['X-CSRF-Token'] = login.json()['csrf_token']
    app.state.resource_transport = lambda *a, **k: pytest.fail("unauthorized SSH")
    assert begin(admin, c, [m["id"]]).status_code == 403
    from dingofs_platform.auth.models import User
    with app.state.session_factory.begin() as db:
        user = db.scalar(select(User).where(User.username == "member"))
        db.get(Cluster, c["id"]).creator_id = user.id
    assert begin(admin, c, [m["id"]]).status_code == 403


def test_scan_validation_is_bounded_and_does_not_accept_shell_input():
    mid = str(uuid4())
    for values in [[], [mid, mid], [str(uuid4()) for _ in range(21)], [";id"]]:
        with pytest.raises(ValueError):
            commands.validate("mount.scan", {"machine_ids": values})
    with pytest.raises(ValueError):
        commands.validate("mount.scan", {"machine_ids": [mid], "command": "id"})
    script = commands.build_script("mount.scan", {"machine_ids": [mid]}, "a:6900", "scan", {})
    compile(shlex.split(script)[2], "remote-scan", "exec")
    assert not commands.is_mutating("mount.scan")
