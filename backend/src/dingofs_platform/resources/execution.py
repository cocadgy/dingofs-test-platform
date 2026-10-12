"""Sequential bounded execution; completed steps are never repeated after sudo auth."""

import json
from copy import deepcopy
import secrets
import time
from datetime import timedelta
from dingofs_platform.db import get_db
from dingofs_platform.auth.models import User, Session
from dingofs_platform.auth.users import actor_in_transaction
from dingofs_platform.auth.service import digest
from dingofs_platform.inventory.models import Machine, Cluster
from dingofs_platform.inventory.permissions import can_manage
from dingofs_platform.inventory.service import lock_inventory, audit
from dingofs_platform.inventory.credentials import decrypt_password
from dingofs_platform.inventory.ssh_transport import SSHConfig, CollectionError
from dingofs_platform.clusters.transport import (
    ClusterCommand,
    ClusterExecutionError,
    AuthenticationRequired,
    execute_cluster,
)
from dingofs_platform.errors import Problem
from .models import ResourceOperation, ManagedResource
from .views import ACTIVE, now, expire, operation_view
from .safety import redact, product_failed
from . import commands, port_planning
from .remote_helper import FS_LIST_MAX_RESPONSE


def valid(db, op):
    actor, session = db.get(User, op.actor_id), db.get(Session, op.session_id)
    c = db.get(Cluster, op.cluster_id)
    if (
        not actor
        or actor.disabled
        or not session
        or session.expires_at <= now()
        or session.user_id != actor.id
    ):
        return False
    if (
        not c
        or c.archived
        or c.binding_state != "verified"
        or c.revision != op.cluster_revision
        or not can_manage(actor, c)
    ):
        return False
    for work in op.steps:
        m = db.get(Machine, work["machine_id"])
        if (
            not m
            or m.archived
            or m.revision != work["machine_revision"]
            or not can_manage(actor, m)
        ):
            return False
    return True


def terminal(db, op, state, code=None):
    op.state, op.error_code = state, code
    op.secret_ciphertext = None
    op.challenge_digest = None
    if op.resource_id:
        r = db.get(ManagedResource, op.resource_id)
        if state == "succeeded":
            status = {
                "cache.create": "running",
                "cache.stop": "stopped",
                "cache.delete": "deleted",
                "mount.create": "mounted",
                "mount.unmount": "unmounted",
            }.get(op.action)
            if op.action == "mount.status":
                status = ((op.result or {}).get("steps") or [{}])[-1].get(
                    "remote_state"
                )
                if status not in ("mounted", "unmounted", "unknown"):
                    status = None
            if status:
                r.state = status
        elif commands.is_mutating(op.action):
            r.state = "partial" if op.cursor else "unknown"
        r.revision += 1
    actor = db.get(User, op.actor_id)
    if actor:
        audit(
            db, actor, "resource_" + state, "resource-operations/" + op.id, [op.action]
        )


def run(request, oid, password=None, *, claimed=False):
    settings = request.app.state.settings
    deadline = time.monotonic() + settings.resource_operation_timeout
    with get_db(request) as db, db.begin():
        lock_inventory(db)
        op = db.get(ResourceOperation, oid)
        if not op or op.state != ("running" if claimed else "pending"):
            return
        expire(db, op)
        if op.state not in ACTIVE:
            return
        if not valid(db, op):
            terminal(db, op, "failed", "stale")
            return
        op.state = "running"
        op.expires_at = now() + timedelta(
            seconds=settings.resource_operation_timeout + 10
        )
        lease = op.lease_token
    while True:
        config = None
        secret_values = []
        with get_db(request) as db, db.begin():
            lock_inventory(db)
            op = db.get(ResourceOperation, oid)
            if op.state != "running" or op.lease_token != lease:
                return
            if not valid(db, op):
                terminal(db, op, "failed", "stale")
                return
            if op.cursor >= len(op.steps):
                failed = op.action in ("fs.delete_batch", "cache.delete_batch", "cache.stop") and any(s.get("failed") for s in (op.result or {}).get("steps", []))
                terminal(db, op, "failed" if failed else "succeeded", "batch_failed" if failed else None)
                return
            work = deepcopy(op.steps[op.cursor])
            if work["action"] in ("cache.plan", "cache.create"):
                work["record"]["reserved_ports"] = sorted(port_planning.reserved_ports(db, work["record"]))
            if work["action"] == "cache.wait_offline":
                completed = {s.get("member_id") for s in (op.result or {}).get("steps", []) if not s.get("failed")}
                work["parameters"] = {"member_ids": [mid for mid in work["parameters"]["member_ids"] if mid in completed]}
                if not work["parameters"]["member_ids"]:
                    op.cursor += 1
                    continue
            cursor = op.cursor
            c = db.get(Cluster, op.cluster_id)
            m = db.get(Machine, work["machine_id"])
            try:
                storage = (
                    json.loads(
                        decrypt_password(
                            op.secret_ciphertext, settings.credential_encryption_key
                        )
                    )
                    if op.secret_ciphertext
                    else {}
                )
                login_password = decrypt_password(
                    m.ssh_password_ciphertext, settings.credential_encryption_key
                )
                config = SSHConfig(
                    m.address,
                    m.ssh_port,
                    m.ssh_user,
                    login_password,
                    settings.ssh_known_hosts,
                )
            except (Problem, ValueError, TypeError):
                terminal(db, op, "failed", "credential_unavailable")
                return
            secret_values = [login_password, password, *storage.values()]
            command_args = {**work["parameters"], **storage}
            resource_id = work.get("resource_id") or op.resource_id or op.id
            account = op.auth_account
            target_name = c.external_name
        result = None
        error = None
        auth_account = None
        last_check = [0.0, False]

        def cancelled():
            if time.monotonic() - last_check[0] >= 0.5:
                with get_db(request) as db:
                    current = db.get(ResourceOperation, oid)
                    last_check[:] = [
                        time.monotonic(),
                        not current
                        or current.state != "running"
                        or current.lease_token != lease
                        or not valid(db, current),
                    ]
            return last_check[1]

        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ClusterExecutionError("timeout")
            script = commands.build_script(
                work["action"],
                command_args,
                work["mds_addr"],
                resource_id,
                record=work["record"],
            )
            command = ClusterCommand(
                "resource",
                work["target_user"],
                target_name,
                expected_home=work["expected_home"],
                resource_script=script,
                resource_requires_dingo=work["action"] != "cache.stop_external",
            )
            transport = getattr(
                request.app.state, "resource_transport", execute_cluster
            )
            if cancelled():
                raise ClusterExecutionError("cancelled")
            max_bytes = (
                max(settings.cluster_max_bytes, FS_LIST_MAX_RESPONSE)
                if work["action"] == "fs.list"
                else settings.cluster_max_bytes
            )
            output = transport(
                config,
                command,
                password=password,
                auth_account=account,
                timeout_s=remaining,
                max_bytes=max_bytes,
                cancelled=cancelled,
            )
            if (
                output.identity.user != work["target_user"]
                or work["expected_home"]
                and output.identity.home != work["expected_home"]
            ):
                raise ClusterExecutionError("invalid_identity")
            if (
                len(output.stdout.encode()) + len(output.stderr.encode())
                > max_bytes
            ):
                raise ClusterExecutionError("output_limit")
            try:
                parsed = json.loads(output.stdout)
            except (ValueError, TypeError):
                # Unstructured output can echo credentials; retain no raw text.
                raise ClusterExecutionError("query_failed") from None
            result = redact(
                dict(
                    machine_id=work["machine_id"],
                    target_user=work["target_user"],
                    returncode=output.returncode,
                    data=parsed.get("data", parsed),
                    remote_state=parsed.get("state"),
                    command_completed=parsed.get("command_completed") is True,
                    stderr=output.stderr,
                    message=parsed.get("message"),
                ),
                secret_values,
                show_storage_keys=work["action"] == "fs.get",
            )
            if output.returncode or product_failed(parsed):
                raise ClusterExecutionError("query_failed")
        except AuthenticationRequired as exc:
            error, auth_account = "needs_password", exc.account
        except (ClusterExecutionError, CollectionError) as exc:
            error = exc.code
        except Exception:
            error = "worker_failed"
        finally:
            password = None
            secret_values.clear()
        with get_db(request) as db, db.begin():
            lock_inventory(db)
            op = db.get(ResourceOperation, oid)
            if op.state != "running" or op.lease_token != lease:
                return
            if not valid(db, op) or op.expires_at <= now():
                terminal(db, op, "interrupted", "stale")
                return
            if error == "needs_password" and op.auth_attempts < 3:
                op.state, op.error_code, op.auth_account = (
                    "needs_password",
                    error,
                    auth_account,
                )
                op.lease_token = secrets.token_hex(24)
                op.challenge_digest = digest(op.lease_token)
                op.expires_at = now() + timedelta(seconds=settings.cluster_auth_seconds)
                return
            if result and op.action in ("cache.plan", "cache.create"):
                data = result.get("data") or {}
                port = data.get("effective_port")
                if port is not None:
                    try:
                        port_planning.store_effective_port(db, op, cursor, port)
                    except ValueError as exc:
                        error = "query_failed"
                        result = {**result, "message": str(exc), "returncode": 1}
                elif not error and op.action == "cache.plan":
                    error = "query_failed"
                    result = {**result, "message": "端口检查未返回有效端口，请重新检查", "returncode": 1}
            if op.action == "cache.stop" and work.get("member_id"):
                result = {**(result or {"message": error, "returncode": None}),
                          "member_id": work["member_id"], "failed": bool(error)}
            elif result and op.action in ("fs.delete_batch", "cache.delete_batch"):
                target_key = "member_id" if op.action == "cache.delete_batch" else "fs_name"
                result = {**result, target_key: work["parameters"][target_key], "failed": bool(error)}
            elif result and work["action"] == "cache.wait_offline":
                result = {**result, "failed": bool(error)}
            if work.get("resource_id") and work.get("member_id"):
                resource = db.get(ManagedResource, work["resource_id"])
                if resource:
                    data = deepcopy(resource.data)
                    for member in data.get("members", []):
                        if member.get("member_id") == work["member_id"]:
                            member["process_state"] = "unknown" if error else "stopped"
                    resource.data = data
                    resource.state = "stopped" if all(m.get("process_state") == "stopped" for m in data.get("members", [])) else "partial"
                    resource.revision += 1
            if result:
                op.result = {"steps": [*(op.result or {}).get("steps", []), result]}
            known_delete_failure = (op.action in ("fs.delete_batch", "cache.delete_batch", "cache.stop") and error == "query_failed"
                                    and result and result.get("remote_state") == "failed"
                                    and result.get("command_completed") is True)
            known_stop_failure = (op.action == "cache.stop" and work.get("member_id")
                                  and error == "query_failed" and result
                                  and result.get("remote_state") == "failed")
            if error and not (known_delete_failure or known_stop_failure):
                terminal(
                    db,
                    op,
                    "failed",
                    "auth_limit" if error == "needs_password" else error,
                )
                return
            op.cursor = cursor + 1
            op.auth_attempts = 0
            op.auth_account = None
            op.challenge_digest = None


def owned(db, request, oid):
    actor = actor_in_transaction(db, request)
    op = db.get(ResourceOperation, oid)
    if not op or op.actor_id != actor.id:
        raise Problem(404, "not_found", "操作不存在或不属于当前用户")
    expire(db, op)
    return op


def authenticate(request, oid, challenge, password, tasks):
    if any(c in password for c in ("\n", "\r", "\x00")):
        raise Problem(422, "invalid_password", "密码不能包含换行或空字符")
    with get_db(request) as db, db.begin():
        lock_inventory(db)
        op = owned(db, request, oid)
        if (
            op.state != "needs_password"
            or not op.challenge_digest
            or not secrets.compare_digest(op.challenge_digest, digest(challenge))
            or not valid(db, op)
        ):
            raise Problem(409, "challenge_stale", "认证请求已失效，请重新开始")
        # Bind the retry to this login session, never another browser login.
        from dingofs_platform.clusters.operations import current_session

        if current_session(db, request, db.get(User, op.actor_id)).id != op.session_id:
            raise Problem(409, "challenge_stale", "请使用发起操作的登录会话认证")
        op.auth_attempts += 1
        op.challenge_digest = None
        op.lease_token = secrets.token_hex(24)
        op.state = "running"
    tasks.add_task(run, request, oid, password=password, claimed=True)
    with get_db(request) as db, db.begin():
        return operation_view(db, owned(db, request, oid), private=True)


def cancel(request, oid):
    with get_db(request) as db, db.begin():
        lock_inventory(db)
        op = owned(db, request, oid)
        if op.state in ACTIVE:
            op.lease_token = secrets.token_hex(24)
            terminal(db, op, "cancelled", "cancelled")
        return operation_view(db, op, private=True)
