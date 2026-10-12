"""Short locked transactions around fixed, bounded remote reads. No stored passwords."""

from datetime import datetime, timedelta, timezone
from dataclasses import asdict
import hashlib
import secrets
import time
from sqlalchemy import select
from dingofs_platform.db import get_db
from dingofs_platform.errors import Problem
from dingofs_platform.auth.models import User, Session
from dingofs_platform.auth.service import digest
from dingofs_platform.inventory.models import Machine, Cluster
from dingofs_platform.inventory.credentials import decrypt_password
from dingofs_platform.inventory.ssh_transport import SSHConfig, CollectionError
from dingofs_platform.inventory.host_trust import scoped_trust, make_challenge
from dingofs_platform.inventory.service import lock_inventory, audit
from .models import ClusterOperation
from .transport import (
    execute_cluster,
    operation_command,
    CONTROL_ACTIONS,
    ClusterCommand,
    AuthenticationRequired,
    ClusterExecutionError,
)
from dingofs_platform.inventory.permissions import can_manage, require_manage
from .parser import parse_cluster_names, parse_cluster_status, ClusterParseError

ACTIVE = ("pending", "running")
MESSAGES = {
    "credential_unavailable": "无法解密 SSH 凭据，请核对平台加密密钥或重新配置机器密码",
    "identity_changed": "执行用户的登录目录已变化，请重新发现并确认管理入口",
    "needs_password": "切换执行用户需要认证，请输入下方指定账号的密码",
    "switch_denied": "没有切换到目标用户的权限",
    "user_missing": "目标用户不存在",
    "dingo_missing": "目标用户的登录环境中找不到 dingo",
    "sudo_missing": "机器未安装 sudo，无法切换用户",
    "login_failed": "无法加载目标用户登录环境",
    "invalid_identity": "执行用户或登录环境校验失败",
    "auth_account_changed": "认证账号已变化，请重新开始操作",
    "authentication_failed": "SSH 认证失败，请检查机器凭据",
    "connection_failed": "SSH 连接失败",
    "timeout": "命令执行超时",
    "output_limit": "命令输出超过限制",
    "worker_failed": "命令执行失败，请检查机器和 dingo 配置",
    "target_mismatch": "返回的集群名称与目标不一致",
    "invalid_listing": "无法识别集群列表",
    "invalid_header": "无法识别集群状态头",
    "invalid_row": "服务表格解析不完整",
    "query_failed": "dingo 命令执行失败",
    "host_key_unknown": "请由机器创建者或管理员核验并信任 SSH 指纹",
    "host_key_changed": "机器 SSH 指纹发生变化，请由机器创建者或管理员核验",
    "stale": "资源配置或登录状态已变化，请重新操作",
    "interrupted": "操作已中断或租约过期，请重试",
    "cancelled": "操作已取消",
    "auth_limit": "认证失败次数已达上限，请重新开始",
}


def now():
    return datetime.now(timezone.utc)


def challenge(op):
    return hashlib.sha256(
        (op.lease_token + ":" + str(op.auth_attempts)).encode()
    ).hexdigest()


def valid_actor(db, op):
    session = db.get(Session, op.session_id)
    actor = db.get(User, op.actor_id)
    return bool(
        session
        and session.user_id == op.actor_id
        and session.expires_at > now()
        and actor
        and not actor.disabled
    )


def current_session(db, request, actor):
    row = db.scalar(
        select(Session).where(
            Session.token_hash == digest(request.cookies.get("session", ""))
        )
    )
    if not row or row.user_id != actor.id or row.expires_at <= now():
        raise Problem(401, "unauthenticated", "请重新登录")
    return row


def expired(op):
    return (op.state in ACTIVE and op.lease_expires_at <= now()) or (
        op.state == "needs_password" and op.expires_at <= now()
    )


def expire(op):
    if expired(op):
        op.state = "interrupted"
        op.error_code = "interrupted"
        op.challenge_digest = None


def view(db, op):
    expire(op)
    machine = db.get(Machine, op.machine_id)
    result = op.result
    if op.kind == "discover" and op.state == "succeeded" and result:
        registered = list(
            db.scalars(
                select(Cluster.external_name).where(
                    Cluster.management_machine_id == op.machine_id,
                    Cluster.os_user == op.target_user,
                )
            )
        )
        result = {**result, "registered_names": registered}
    return dict(
        id=op.id,
        kind=op.kind,
        parameters=op.parameters,
        state=op.state,
        machine_id=op.machine_id,
        machine_name=machine.name,
        ssh_user=machine.ssh_user,
        target_user=op.target_user,
        cluster_id=op.cluster_id,
        error_code=op.error_code,
        message=MESSAGES.get(op.error_code, "操作失败") if op.error_code else None,
        result=result,
        auth_account=op.auth_account if op.state == "needs_password" else None,
        challenge=challenge(op) if op.state == "needs_password" else None,
        expires_at=op.expires_at.isoformat(),
    )


def load_owned(db, id, actor):
    op = db.get(ClusterOperation, id)
    if not op:
        raise Problem(404, "not_found", "操作不存在")
    if op.actor_id != actor.id:
        raise Problem(403, "forbidden", "不能访问其他用户的操作")
    expire(op)
    return op


def check_target(db, op):
    m = db.get(Machine, op.machine_id)
    c = db.get(Cluster, op.cluster_id) if op.cluster_id else None
    return bool(
        m
        and not m.archived
        and m.revision == op.machine_revision
        and valid_actor(db, op)
        and can_manage(db.get(User, op.actor_id), c if c else m)
        and (
            not op.cluster_id
            or c
            and not c.archived
            and c.revision == op.cluster_revision
            and c.management_machine_id == m.id
            and c.os_user == op.target_user
            and c.binding_state == "verified"
        )
    )


def start_operation(
    request,
    actor,
    *,
    kind,
    machine_id,
    machine_revision,
    target_user,
    cluster_id=None,
    cluster_revision=None,
    parameters=None,
):
    settings = request.app.state.settings
    with get_db(request) as db, db.begin():
        lock_inventory(db)
        session = current_session(db, request, actor)
        actual = db.get(User, actor.id)
        if not actual or actual.disabled:
            raise Problem(403, "forbidden", "账号不存在或已禁用")
        machine = db.get(Machine, machine_id)
        if not machine or machine.archived:
            raise Problem(422, "invalid_reference", "机器不存在或已归档")
        if machine.revision != machine_revision:
            raise Problem(409, "revision_conflict", "机器配置已更新，请重新选择")
        if kind == "discover":
            require_manage(actual, machine)
        if not machine.ssh_password_ciphertext:
            raise Problem(422, "ssh_password_missing", "请先为机器配置 SSH 密码")
        if cluster_id:
            c = db.get(Cluster, cluster_id)
            if not c or c.archived or c.binding_state != "verified":
                raise Problem(409, "binding_required", "请先发现集群并确认管理入口")
            require_manage(actual, c)
            if c.revision != cluster_revision:
                raise Problem(409, "revision_conflict", "集群配置已更新")
        if cluster_id:
            from dingofs_platform.resources.models import ResourceOperation
            from dingofs_platform.resources.views import (
                expire as expire_resource, ACTIVE as RESOURCE_ACTIVE,
            )

            for resource_op in db.scalars(
                select(ResourceOperation).where(
                    ResourceOperation.cluster_id == cluster_id,
                    ResourceOperation.state.in_(RESOURCE_ACTIVE),
                )
            ):
                expire_resource(db, resource_op)
                if resource_op.state in RESOURCE_ACTIVE:
                    raise Problem(409, "resource_busy", "此集群有进行中的资源操作")
        if kind in CONTROL_ACTIONS:
            validate_control(c, parameters)
        ops = list(
            db.scalars(
                select(ClusterOperation).where(
                    ClusterOperation.machine_id == machine_id,
                    ClusterOperation.state.in_((*ACTIVE, "needs_password")),
                )
            )
        )
        for op in ops:
            expire(op)
        for op in ops:
            if (
                op.state in (*ACTIVE, "needs_password")
                and cluster_id
                and op.cluster_id == cluster_id
                and (kind in CONTROL_ACTIONS or op.kind in CONTROL_ACTIONS)
            ):
                if (
                    op.actor_id == actor.id
                    and op.kind == kind
                    and op.parameters == parameters
                ):
                    return view(db, op), False
                raise Problem(409, "operation_busy", "集群有进行中的操作，请完成后再试")
            if (
                op.state in (*ACTIVE, "needs_password")
                and cluster_id
                and op.cluster_id == cluster_id
                and op.kind == kind
            ):
                if op.actor_id == actor.id:
                    return view(db, op), False
                if op.state == "needs_password":
                    continue
                raise Problem(409, "operation_busy", "集群正在采集，请稍后重试")
        if (
            sum(op.state in ACTIVE for op in ops)
            >= settings.cluster_machine_concurrency
        ):
            raise Problem(409, "machine_busy", "该机器正在执行其他查询，请稍后重试")
        ttl = (
            settings.cluster_discovery_timeout
            if kind == "discover"
            else settings.cluster_control_timeout
            if kind in CONTROL_ACTIONS
            else settings.cluster_status_timeout
        )
        op = ClusterOperation(
            actor_id=actor.id,
            session_id=session.id,
            kind=kind,
            parameters=parameters,
            machine_id=machine_id,
            machine_revision=machine_revision,
            target_user=target_user,
            cluster_id=cluster_id,
            cluster_revision=cluster_revision,
            state="pending",
            lease_token=secrets.token_hex(24),
            lease_expires_at=now() + timedelta(seconds=ttl + 10),
            expires_at=now() + timedelta(seconds=settings.cluster_discovery_seconds),
            auth_attempts=0,
        )
        db.add(op)
        db.flush()
        if cluster_id and kind == "status":
            c.status_attempt_at = now()
            c.status_attempt_state = "pending"
            c.status_error_code = None
        audit(db, actor, "cluster_" + kind, "cluster-operations/" + op.id, [])
        return view(db, op), True


def run_operation(request, operation_id, *, password=None, claimed=False):
    settings = request.app.state.settings
    with get_db(request) as db, db.begin():
        lock_inventory(db)
        op = db.get(ClusterOperation, operation_id)
        # A queued job cannot renew an expired lease. Password retries have
        # already been authorized against their separate challenge deadline.
        if op and not claimed:
            expire(op)
        if not op or op.state != ("running" if claimed else "pending"):
            return
        if not check_target(db, op):
            op.state = "failed"
            op.error_code = "stale"
            return
        op.state = "running"
        op.started_at = now()
        token = op.lease_token
        ttl = (
            settings.cluster_discovery_timeout
            if op.kind == "discover"
            else settings.cluster_control_timeout
            if op.kind in CONTROL_ACTIONS
            else settings.cluster_status_timeout
        )
        op.lease_expires_at = now() + timedelta(seconds=ttl + 5)
        m = db.get(Machine, op.machine_id)
        cluster = db.get(Cluster, op.cluster_id) if op.cluster_id else None
        try:
            ssh_password = decrypt_password(
                m.ssh_password_ciphertext, settings.credential_encryption_key
            )
        except Problem:
            op.state = "failed"
            op.error_code = "credential_unavailable"
            op.finished_at = now()
            if cluster and op.kind == "status":
                cluster.status_attempt_state = "failed"
                cluster.status_error_code = "credential_unavailable"
            return
        expected_home = cluster.execution_home if cluster else None
        config = SSHConfig(
            m.address,
            m.ssh_port,
            m.ssh_user,
            ssh_password,
            settings.ssh_known_hosts,
            scoped_trust(m),
        )
        command = ClusterCommand(
            op.kind,
            op.target_user,
            cluster.external_name if cluster else None,
            **(op.parameters or {}),
            expected_home=expected_home,
        )
        auth_account = op.auth_account
    last = [0.0]
    cancelled_cache = [False]

    def cancelled():
        if time.monotonic() - last[0] > 0.5:
            last[0] = time.monotonic()
            with get_db(request) as db:
                row = db.get(ClusterOperation, operation_id)
                cancelled_cache[0] = (
                    not row
                    or row.state != "running"
                    or row.lease_token != token
                    or not check_target(db, row)
                )
        return cancelled_cache[0]

    result = None
    code = None
    account = None
    host_key = None
    try:
        transport = getattr(request.app.state, "cluster_transport", execute_cluster)
        output = transport(
            config,
            command,
            password=password,
            auth_account=auth_account,
            timeout_s=ttl,
            max_bytes=settings.cluster_max_bytes,
            cancelled=cancelled,
        )
        raw = output.stdout
        err = output.stderr
        for secret in (config.password, password):
            if secret:
                raw = raw.replace(secret, "[REDACTED]")
                err = err.replace(secret, "[REDACTED]")
        if len(raw.encode()) + len(err.encode()) > settings.cluster_max_bytes:
            raise ClusterExecutionError("output_limit")
        result = {
            "executed_commands": [{"command": operation_command(command), "status": "completed"}],
            "identity": asdict(output.identity),
            "stdout": raw,
            "stderr": err,
            "returncode": output.returncode,
        }
        if (
            output.identity.user != command.target_user
            or not output.identity.home.startswith("/")
        ):
            raise ClusterExecutionError("invalid_identity")
        if expected_home and output.identity.home != expected_home:
            raise ClusterExecutionError("identity_changed")
        if output.returncode != 0:
            raise ClusterExecutionError("query_failed")
        if command.kind == "discover":
            result["names"] = parse_cluster_names(raw)
        elif command.kind == "status":
            result["snapshot"] = parse_cluster_status(
                raw, command.cluster_name
            ).model_dump()
    except AuthenticationRequired as e:
        code = "needs_password"
        account = e.account
        result = None
    except CollectionError as e:
        code = e.code
        host_key = e.host_key
    except (ClusterExecutionError, ClusterParseError) as e:
        code = e.code
    except Exception:
        code = "worker_failed"
        result = None
    finally:
        password = None
    with get_db(request) as db, db.begin():
        lock_inventory(db)
        op = db.get(ClusterOperation, operation_id)
        if not op or op.state != "running" or op.lease_token != token:
            return
        if not check_target(db, op) or op.lease_expires_at <= now():
            code = "stale"
            result = None
        op.result = result
        op.error_code = code
        op.finished_at = now()
        op.challenge_digest = None
        if code == "needs_password" and op.auth_attempts < 3:
            op.state = "needs_password"
            op.auth_account = account
            op.expires_at = now() + timedelta(seconds=settings.cluster_auth_seconds)
            op.challenge_digest = digest(challenge(op))
        elif code in ("host_key_unknown", "host_key_changed") and host_key:
            op.state = "needs_trust"
            m = db.get(Machine, op.machine_id)
            m.ssh_trust_pending = make_challenge(m, host_key)
        else:
            op.state = "failed" if code else "succeeded"
            if code == "needs_password":
                op.error_code = "auth_limit"
            if not code:
                op.expires_at = now() + timedelta(
                    seconds=settings.cluster_discovery_seconds
                )
        if op.cluster_id and op.kind == "status":
            c = db.get(Cluster, op.cluster_id)
            if c and c.revision == op.cluster_revision:
                c.status_attempt_at = op.finished_at
                c.status_attempt_state = op.state
                c.status_error_code = op.error_code
                c.status_output = (
                    {
                        k: result[k]
                        for k in ("stdout", "stderr", "returncode")
                        if k in result
                    }
                    if result
                    else None
                )
                if op.state == "succeeded":
                    c.status_snapshot = result["snapshot"]
                    c.status_success_at = op.finished_at
        actor = db.get(User, op.actor_id)
        if actor:
            audit(db, actor, "cluster_" + op.state, "cluster-operations/" + op.id, [])


def resume_operation(request, actor, id, challenge_value, password):
    settings = request.app.state.settings
    with get_db(request) as db, db.begin():
        lock_inventory(db)
        current_session(db, request, actor)
        op = load_owned(db, id, actor)
        if (
            op.state != "needs_password"
            or not op.challenge_digest
            or not secrets.compare_digest(op.challenge_digest, digest(challenge_value))
            or not check_target(db, op)
        ):
            raise Problem(409, "challenge_stale", "认证请求已失效，请重新开始")
        if "\n" in password or "\r" in password or "\x00" in password:
            raise Problem(422, "invalid_password", "密码不能包含换行或空字符")
        active = list(
            db.scalars(
                select(ClusterOperation).where(
                    ClusterOperation.machine_id == op.machine_id,
                    ClusterOperation.state.in_(ACTIVE),
                )
            )
        )
        for a in active:
            expire(a)
        if sum(
            a.state in ACTIVE for a in active
        ) >= settings.cluster_machine_concurrency or any(
            a.state in ACTIVE and op.cluster_id and a.cluster_id == op.cluster_id
            for a in active
        ):
            raise Problem(409, "machine_busy", "机器或集群正在采集，请稍后重试")
        op.challenge_digest = None
        op.auth_attempts += 1
        op.lease_token = secrets.token_hex(24)
        op.state = "running"
    run_operation(request, id, password=password, claimed=True)
    with get_db(request) as db, db.begin():
        return view(db, load_owned(db, id, actor))


def cancel_operation(request, actor, id):
    with get_db(request) as db, db.begin():
        lock_inventory(db)
        op = db.get(ClusterOperation, id)
        if not op:
            raise Problem(404, "not_found", "操作不存在")
        if op.actor_id != actor.id and actor.role != "admin":
            raise Problem(403, "forbidden", "不能取消此操作")
        if op.state in (*ACTIVE, "needs_password", "needs_trust"):
            op.state = "cancelled"
            op.error_code = "cancelled"
            op.challenge_digest = None
            op.lease_token = secrets.token_hex(24)
            if op.cluster_id and op.kind == "status":
                c = db.get(Cluster, op.cluster_id)
                if c and c.revision == op.cluster_revision:
                    c.status_attempt_state = "cancelled"
                    c.status_error_code = "cancelled"
        return view(db, op)


def validate_control(cluster, parameters):
    if not cluster or not parameters:
        raise Problem(422, "invalid_target", "缺少操作目标")
    scope, target = parameters.get("scope"), parameters.get("target")
    if scope == "all" and target is None:
        return
    field = {"service": "id", "role": "role"}.get(scope)
    services = (cluster.status_snapshot or {}).get("services", [])
    if not field or not target or target not in {row[field] for row in services}:
        raise Problem(422, "invalid_target", "请选择当前集群中已采集的服务或角色")
