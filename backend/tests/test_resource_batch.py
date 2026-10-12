"""Exercise the worker loop with an isolated in-memory operation and transport."""
import json
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace as NS

import pytest

from dingofs_platform.resources import execution as worker


@pytest.mark.parametrize("action,key,step_action", [("fs.delete_batch", "fs_name", "fs.delete"), ("cache.delete_batch", "member_id", "cache.delete")])
@pytest.mark.parametrize("failure,expected_calls,expected_state", [
    (None, 3, "succeeded"),
    ("completed", 3, "failed"),
    ("timeout", 2, "failed"),
])
def test_batch_worker_preserves_targets_and_handles_failure(monkeypatch, failure, expected_calls, expected_state, action, key, step_action):
    targets = ["test-a", "test-b", "test-c"]
    op = NS(state="pending", lease_token="lease", cursor=0, action=action,
            steps=[dict(machine_id="m", target_user="root", expected_home="/root", action=step_action,
                        parameters={key: name}, mds_addr="host:6900", record=None) for name in targets],
            result={"steps": []}, cluster_id="c", secret_ciphertext=None, resource_id=None,
            id="op", auth_account=None, auth_attempts=0, expires_at=worker.now()+timedelta(minutes=10))
    machine = NS(address="localhost", ssh_port=22, ssh_user="root", ssh_password_ciphertext=None)
    class DB:
        def get(self, model, key):
            return op if key == "op" else machine if key == "m" else NS(external_name="cluster")
        @contextmanager
        def begin(self):
            yield self
    @contextmanager
    def db(_request):
        yield DB()
    monkeypatch.setattr(worker, "get_db", db)
    monkeypatch.setattr(worker, "lock_inventory", lambda db: None)
    monkeypatch.setattr(worker, "valid", lambda db, op: True)
    monkeypatch.setattr(worker, "expire", lambda db, op: None)
    monkeypatch.setattr(worker, "decrypt_password", lambda *args: None)
    def terminal(db, op, state, code=None):
        op.state, op.error_code = state, code
    monkeypatch.setattr(worker, "terminal", terminal)
    calls = []
    monkeypatch.setattr(worker.commands, "build_script", lambda action, p, *args, **kw: p[key])
    def transport(config, command, **kwargs):
        calls.append(command.resource_script)
        failed = len(calls) == 2 and failure is not None
        if failed and failure == "timeout":
            raise worker.ClusterExecutionError("timeout")
        return NS(identity=NS(user="root", home="/root"), returncode=int(failed), stderr="", stdout=json.dumps({
            "state": "failed" if failed else "succeeded", "command_completed": failed,
            "data": {"message": "mounted" if failed else "deleted"},
        }))
    settings = NS(resource_operation_timeout=600, credential_encryption_key="", ssh_known_hosts="/unused", cluster_max_bytes=100000)
    request = NS(app=NS(state=NS(settings=settings, resource_transport=transport)))
    worker.run(request, "op")
    assert calls == targets[:expected_calls]
    assert op.state == expected_state
    assert [step[key] for step in op.result["steps"]] == targets[:(1 if failure == "timeout" else 3)]
    if failure == "completed":
        assert [step["failed"] for step in op.result["steps"]] == [False, True, False]
        assert op.error_code == "batch_failed"
