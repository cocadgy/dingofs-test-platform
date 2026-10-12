"""Authorize targets and reserve immutable work before any SSH is attempted."""

import hashlib
import json
import secrets
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select
from dingofs_platform.db import get_db
from dingofs_platform.errors import Problem
from dingofs_platform.auth.users import actor_in_transaction
from dingofs_platform.clusters.operations import current_session
from dingofs_platform.inventory.models import Cluster, Machine
from dingofs_platform.inventory.permissions import require_manage, can_manage
from dingofs_platform.inventory.service import lock_inventory, audit
from dingofs_platform.inventory.credentials import encrypt_password
from .models import ManagedResource, ResourceOperation
from dingofs_platform.cache_profiles import service as cache_profiles
from dingofs_platform.mount_profiles import service as mount_profiles
from dingofs_platform.cache_profiles.catalog import MEMBER_KEYS, INDEX as CACHE_PARAMETER_INDEX, member_defaults
from dingofs_platform.storage import service as storage_profiles
from .views import check_busy, now, operation_view, resource_view
from . import commands
from . import port_planning, external_cache


def cluster(db, cid):
    c = db.get(Cluster, cid)
    if not c or c.archived:
        raise Problem(404, "not_found", "集群不存在或已归档")
    return c


def machine(db, actor, mid):
    m = db.get(Machine, mid)
    if not m or m.archived:
        raise Problem(422, "invalid_machine", "执行机器不存在或已归档")
    require_manage(actor, m)
    if not m.ssh_password_ciphertext:
        raise Problem(422, "ssh_password_missing", "请先配置执行机器的 SSH 密码")
    return m


def step(db, actor, c, action, params, *, record=None, mid=None, user=None):
    m = machine(db, actor, mid or c.management_machine_id)
    user = user or c.os_user
    return dict(
        machine_id=m.id,
        machine_revision=m.revision,
        target_user=user,
        expected_home=c.execution_home
        if m.id == c.management_machine_id and user == c.os_user
        else None,
        action=action,
        parameters=params,
        record=record,
    )


def prepare(db, actor, c, action, p):
    if action in ("cache.leave", "cache.unlock", "cache.weight"):
        return [step(db, actor, c, action, p)], None
    if action == "cache.stop" and "member_ids" in p:
        # A named group may span many independent creation records. Resolve
        # every UUID before authorizing any work, preserving each owner's ID.
        resources = db.scalars(select(ManagedResource).where(
            ManagedResource.cluster_id == c.id, ManagedResource.kind == "cache",
            ManagedResource.state.notin_(("deleted", "planned"))))
        matches = {}
        for resource in resources:
            for member in resource.data.get("members", []):
                if member.get("member_id") in p["member_ids"]:
                    matches.setdefault(member["member_id"], []).append((resource, member))
        duplicates = [mid for mid in p["member_ids"] if len(matches.get(mid, [])) > 1]
        if duplicates:
            raise Problem(422, "ambiguous_member", "成员存在重复的进程管理记录：" + ", ".join(duplicates))
        missing = [mid for mid in p["member_ids"] if mid not in matches]
        external = external_cache.resolve_members(db, actor, c, missing) if missing else {}
        work = []
        for mid in p["member_ids"]:
            if mid in external:
                target = external[mid]
                item = step(db, actor, c, "cache.stop_external", {"member_id": mid},
                            record={**target["record"], "force_stop": p.get("force", False)}, mid=target["machine_id"], user="root")
                item["member_id"] = mid
                work.append(item)
                continue
            resource, member = matches[mid][0]
            item = step(db, actor, c, "cache.stop", {"resource_id": resource.id},
                        record={**member, "force_stop": p.get("force", False)}, mid=member["machine_id"], user=member["target_user"])
            item["resource_id"] = resource.id
            item["member_id"] = mid
            work.append(item)
        if external:
            work.insert(0, step(db, actor, c, "cache.verify_members", {"member_ids": list(external)},
                                record={"members": [target["record"] for target in external.values()]}))
        # Process exit completes stop; MDS heartbeat expiry is asynchronous.
        return work, None
    if action == "cache.delete_batch":
        return [step(db, actor, c, "cache.delete", {"member_id": member}) for member in p["member_ids"]], None
    if action == "fs.delete_batch":
        return [step(db, actor, c, "fs.delete", {"fs_name": name}) for name in p["fs_names"]], None
    if action == "cache.delete" and "member_id" in p:
        # Deleting an MDS registration only needs the verified cluster entry.
        # It does not grant process access to the member's host.
        return [step(db, actor, c, action, p)], None
    if action == "cache.create" and "plan_id" in p:
        return port_planning.consume(db, actor, c, p["plan_id"])
    resource = None
    if action in ("cache.create", "cache.plan", "mount.create"):
        rid = str(uuid4())
        root = "/" + c.id + "/" + rid
        if action in ("cache.create", "cache.plan"):
            members = []
            seen = set()
            for data in p["members"]:
                identity = (data["machine_id"], data["listen_port"])
                if data.get("port_mode", "manual") == "manual" and identity in seen:
                    raise Problem(
                        422, "duplicate_member", "同一机器的成员监听端口不能重复"
                    )
                if data.get("port_mode", "manual") == "manual":
                    seen.add(identity)
                member_id = data.get("member_id") or str(uuid4())
                if data.get("member_id"):
                    existing = db.scalars(select(ManagedResource).where(ManagedResource.cluster_id == c.id, ManagedResource.kind == "cache", ManagedResource.state != "deleted"))
                    if any(any(m.get("member_id") == member_id for m in r.data.get("members", [])) for r in existing):
                        raise Problem(422, "duplicate_member", "成员 ID 已被平台记录占用，请使用其他 ID")
                member = dict(
                    data,
                    group_name=p["group_name"],
                    member_id=member_id,
                    cache_expire_s=p.get("cache_expire_s", 259200),
                    cache_options={k:v for k,v in p.get("cache_options", {}).items() if k not in MEMBER_KEYS},
                    cache_dir=data["cache_dir"].rstrip("/") + "/" + member_id,
                    state_dir="/tmp/dingofs-platform-resources-"
                    + data["target_user"]
                    + root
                    + "/"
                    + member_id,
                    log_dir="/tmp/dingofs-platform-resources-"
                    + data["target_user"]
                    + root
                    + "/"
                    + member_id
                    + "/logs",
                )
                members.append(member)
            for item in members:
                item["allowed_member_ids"] = [m["member_id"] for m in members]
            data = dict(group_name=p["group_name"], members=members)
            name, kind = p["group_name"], "cache"
            work = [
                step(
                    db,
                    actor,
                    c,
                    action,
                    m,
                    record=m,
                    mid=m["machine_id"],
                    user=m["target_user"],
                )
                for m in members
            ]
        else:
            root = "/tmp/dingofs-platform-resources-" + p["target_user"] + root
            data = dict(p, state_dir=root, log_dir=root + "/logs")
            name, kind = p["mount_path"], "mount"
            work = [
                step(
                    db,
                    actor,
                    c,
                    action,
                    p,
                    record=data,
                    mid=p["machine_id"],
                    user=p["target_user"],
                )
            ]
        # Cache names identify groups; each request adds independently owned members.
        # Only mount paths must be unique on the same machine.
        if kind == "mount":
            rows = db.scalars(
                select(ManagedResource).where(
                    ManagedResource.cluster_id == c.id,
                    ManagedResource.kind == "mount",
                    ManagedResource.name == name,
                    ManagedResource.state.notin_(("deleted", "unmounted")),
                )
            )
            for existing in rows:
                if existing.data["machine_id"] == data["machine_id"]:
                    raise Problem(409, "resource_exists", "此机器上的挂载目录已经登记")
        resource = ManagedResource(
            id=rid,
            cluster_id=c.id,
            creator_id=actor.id,
            kind=kind,
            name=name,
            state="planned" if action == "cache.plan" else "pending",
            data=data,
        )
        db.add(resource)
        db.flush()
        if kind == "cache":
            port_planning.reserve(db, resource, work)
        return work, resource
    if action.startswith(("cache.", "mount.")) and action not in ("cache.list",):
        resource = db.get(ManagedResource, p.get("resource_id"))
        kind = action.split(".")[0]
        if (
            not resource
            or resource.cluster_id != c.id
            or resource.kind != kind
            or resource.state in ("deleted", "planned")
        ):
            raise Problem(422, "invalid_resource", "请选择当前集群由平台管理的资源")
        rows = resource.data["members"] if kind == "cache" else [resource.data]
        return [
            step(
                db,
                actor,
                c,
                action,
                p,
                record=r,
                mid=r["machine_id"],
                user=r["target_user"],
            )
            for r in rows
        ], resource
    return [step(db, actor, c, action, p)], None


def create(request, cid, payload):
    try:
        p = commands.validate(payload.action, payload.parameters)
    except (ValueError, TypeError, KeyError) as exc:
        message = "请检查所选操作的必填项、路径和参数范围"
        # Only describe known schema fields; never echo submitted values or unknown keys.
        key, _, reason = str(exc).partition(": ")
        fields = {field["key"]: field["label"] for action in commands.catalog() for field in action["fields"]}
        fields.update({field["key"]: field["label"] for field in commands.schemas.MEMBER_FIELDS})
        fields.update({name: field["label"] for name,field in CACHE_PARAMETER_INDEX.items()})
        reasons = {
            "required": "必填项不能为空",
            "invalid name": "名称须以字母或数字开头，只能包含字母、数字、下划线、点、冒号或连字符",
            "invalid account": "请输入有效的 Linux 用户名，不要包含空格",
            "invalid IP address": "请输入有效的 IP 地址",
            "requires an absolute normalized path": "请输入绝对路径，不要包含重复斜杠、. 或 .. 路径段",
            "choose a dedicated data directory": "请使用专用数据子目录，不能直接使用 /tmp、/mnt 等根目录",
            "required when RDMA is enabled": "开启 RDMA 时必须填写设备名称",
            "invalid string": "文本格式或长度不符合要求",
            "provide between 1 and 32 members": "成员数量必须为 1–32 个",
            "duplicate listen endpoint": "成员的监听地址和端口不能重复",
        }
        if key in fields:
            detail = reason if key in CACHE_PARAMETER_INDEX else reasons.get(reason)
            if detail is None and reason.startswith("requires an integer in ["):
                detail = "必须填写范围内的整数：" + reason.removeprefix("requires an integer in ")
            message = f"参数校验失败：{fields[key]}（{key}）—{detail or '参数格式或范围不符合要求'}"
        raise Problem(422, "invalid_parameters", message) from None
    if commands.is_mutating(payload.action) and not payload.confirmed:
        raise Problem(422, "confirmation_required", "请确认本次操作的目标和影响")
    fingerprint = hashlib.sha256(
        json.dumps([payload.action, p, payload.base_revision], sort_keys=True).encode()
    ).hexdigest()
    with get_db(request) as db, db.begin():
        actor = actor_in_transaction(db, request)
        lock_inventory(db)
        c = cluster(db, cid)
        require_manage(actor, c)
        session = current_session(db, request, actor)
        previous = db.scalar(
            select(ResourceOperation).where(
                ResourceOperation.actor_id == actor.id,
                ResourceOperation.cluster_id == cid,
                ResourceOperation.request_id == str(payload.request_id),
            )
        )
        if previous:
            if previous.request_digest != fingerprint:
                raise Problem(409, "request_conflict", "同一请求标识不能用于不同操作")
            return operation_view(db, previous, private=True), False
        if c.revision != payload.base_revision:
            raise Problem(409, "revision_conflict", "集群配置已更新，请刷新页面")
        if c.binding_state != "verified":
            raise Problem(409, "binding_required", "请先发现并确认集群管理入口")
        addresses = (c.status_snapshot or {}).get("mds_addresses", [])
        if not addresses or not all(
            isinstance(a, str) and a and not any(ord(x) < 32 for x in a)
            for a in addresses
        ):
            raise Problem(422, "mds_missing", "请先成功采集集群状态以获取 MDS 地址")
        check_busy(db, cid)
        source = {}
        if payload.action == "fs.create" and p.get("storage_profile_id"):
            connection, source = storage_profiles.resolve(
                db, p["storage_profile_id"], p["storage_profile_revision"],
                request.app.state.settings.credential_encryption_key,
            )
            p = commands.validate("fs.create", {
                "fs_name": p["fs_name"], "partition_type": p["partition_type"],
                **connection,
            })
        if payload.action in ("cache.create", "cache.plan") and "plan_id" not in p:
            options = p.get("cache_options", {})
            if p.get("cache_profile_id"):
                saved, source = cache_profiles.resolve(db, p["cache_profile_id"], p["cache_profile_revision"])
                if "cache_options" not in payload.parameters:
                    options = saved
            defaults = member_defaults(options)
            # Explicit per-member values win; the template only supplies omissions.
            members = []
            for normalized, raw in zip(p["members"], payload.parameters["members"]):
                members.append({**normalized, **{key:value for key,value in defaults.items() if key not in raw}})
            try:
                p = commands.validate(payload.action, {
                    "group_name": p["group_name"], "members": members,
                    "cache_options": options,
                    "cache_profile_id": p.get("cache_profile_id", ""),
                    "cache_profile_revision": p.get("cache_profile_revision", 0),
                })
            except (ValueError, TypeError, KeyError) as exc:
                raise Problem(422, "invalid_parameters", "缓存配置应用失败，请检查成员目录、容量及 RDMA 设置：" + str(exc)) from None
        if payload.action == "mount.create":
            if p.get("mount_profile_id"):
                saved, source = mount_profiles.resolve(db, p["mount_profile_id"], p["mount_profile_revision"])
                if "mount_options" not in payload.parameters:
                    p["mount_options"] = saved
        secret = {k: p[k] for k in commands.secret_keys(payload.action) if p.get(k)}
        public = {k: v for k, v in p.items() if k not in secret}
        steps, resource = prepare(db, actor, c, payload.action, public)
        if resource and source and payload.action in ("cache.create", "cache.plan", "mount.create"):
            resource.data = {**resource.data, **source}
        # The public specification never includes S3/RADOS secrets.
        for work in steps:
            work["mds_addr"] = ",".join(addresses)
        op = ResourceOperation(
            cluster_id=cid,
            cluster_revision=c.revision,
            actor_id=actor.id,
            session_id=session.id,
            request_id=str(payload.request_id),
            request_digest=fingerprint,
            action=payload.action,
            parameters={**public, **source},
            secret_ciphertext=encrypt_password(
                json.dumps(secret), request.app.state.settings.credential_encryption_key
            )
            if secret
            else None,
            steps=steps,
            state="pending",
            lease_token=secrets.token_hex(24),
            resource_id=resource.id if resource else None,
            cursor=0,
            auth_attempts=0,
            expires_at=now()
            + timedelta(
                seconds=request.app.state.settings.resource_operation_timeout + 15
            ),
            result={"steps": []},
        )
        db.add(op)
        db.flush()
        audit(
            db,
            actor,
            "resource_start",
            "resource-operations/" + op.id,
            [payload.action],
        )
        return operation_view(db, op, private=True), True


def inventory(request, cid):
    with get_db(request) as db, db.begin():
        actor = actor_in_transaction(db, request)
        lock_inventory(db)
        c = cluster(db, cid)
        resources = list(
            db.scalars(
                select(ManagedResource)
                .where(ManagedResource.cluster_id == cid)
                .order_by(ManagedResource.created_at)
            )
        )
        operations = list(
            db.scalars(
                select(ResourceOperation)
                .where(ResourceOperation.cluster_id == cid)
                .order_by(ResourceOperation.created_at.desc())
                .limit(50)
            )
        )
        views = [
            operation_view(db, op, private=op.actor_id == actor.id) for op in operations
        ]
        return dict(
            catalog=commands.catalog(),
            cache_member_targets=external_cache.public_targets(db, actor, c),
            storage_profiles=storage_profiles.listing(db, actor),
            mount_profiles=mount_profiles.listing(db, actor),
            mount_parameter_catalog=mount_profiles.catalog(),
            cache_profiles=cache_profiles.listing(db, actor),
            cache_parameter_catalog=cache_profiles.catalog(),
            machines=[
                dict(
                    id=m.id,
                    name=m.name,
                    address=m.address,
                    ssh_user=m.ssh_user,
                    can_manage=can_manage(actor, m),
                )
                for m in db.scalars(
                    select(Machine)
                    .where(Machine.archived == False)
                    .order_by(Machine.name)
                )
            ],
            resources=[resource_view(r) for r in resources],
            operations=views,
        )
