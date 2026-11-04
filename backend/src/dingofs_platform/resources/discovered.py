"""Persist successfully discovered resources without depending on their creator."""
from copy import deepcopy
from uuid import uuid4

from sqlalchemy import select

from .models import ManagedResource
from .views import now


def body(value):
    return value.get("result", value) if isinstance(value, dict) else value


def records(db, cluster_id, kind):
    return list(db.scalars(select(ManagedResource).where(
        ManagedResource.cluster_id == cluster_id, ManagedResource.kind == kind,
        ManagedResource.state != "deleted")))


def save(db, op, existing, kind, name, state, data):
    if existing is None:
        existing = ManagedResource(id=str(uuid4()), cluster_id=op.cluster_id,
            creator_id=op.actor_id, kind=kind, name=name, state=state, data=data)
        db.add(existing)
    else:
        existing.state, existing.data = state, data
        existing.revision += 1
    db.flush()
    return existing


def persist(db, op, work, result):
    data = result.get("data") or {}
    timestamp = now().isoformat()
    if op.action == "mount.scan":
        existing = records(db, op.cluster_id, "mount")
        for row in data.get("mounts", []):
            if row.get("cluster_match") != "current" or row.get("adoption_error"):
                continue
            identity = row.get("identity")
            if not identity or not identity.get("start_ticks") or not row.get("client_user"):
                row["reason"] = "已确认集群，但客户端身份信息不完整，请重新扫描"
                continue
            matches = [r for r in existing if r.name == row["mount_path"]
                       and r.data.get("machine_id") == work["machine_id"]]
            if len(matches) > 1:
                row["reason"] = "平台存在重复挂载记录，请先处理重复记录"
                continue
            saved = matches[0] if matches else None
            # Platform-created clients retain their private launch/ownership state.
            if saved and saved.data.get("origin") != "external":
                row["saved_resource_id"] = saved.id
                continue
            rid = saved.id if saved else row.get("adopted_resource_id")
            if not rid:
                row["reason"] = "未保存客户端启动信息，请重新扫描"
                continue
            state_dir = f"/tmp/dingofs-platform-resources-root/{op.cluster_id}/{rid}"
            record = dict(origin="external", machine_id=work["machine_id"],
                target_user="root", client_user=row["client_user"],
                fs_name=row["fs_name"], mount_path=row["mount_path"],
                state_dir=state_dir, log_dir=row.get("log_dir") or "",
                identity=identity, discovered_at=timestamp)
            if saved is None:
                saved = ManagedResource(id=rid, cluster_id=op.cluster_id,
                    creator_id=op.actor_id, kind="mount", name=row["mount_path"],
                    state="mounted", data=record)
                db.add(saved)
                db.flush()
                existing.append(saved)
            else:
                save(db, op, saved, "mount", saved.name, "mounted", record)
            row["saved_resource_id"] = saved.id
            row["reason"] = "当前集群挂载，已保存为平台记录"
        visible_paths = {row.get("mount_path") for row in data.get("mounts", [])}
        for saved in existing:
            if (saved.data.get("origin") == "external"
                    and saved.data.get("machine_id") == work["machine_id"]
                    and saved.name not in visible_paths and saved.state == "mounted"):
                saved.state = "unmounted"
                saved.revision += 1
    elif op.action == "fs.list":
        payload = body(data)
        rows = payload if isinstance(payload, list) else payload.get("fs_infos") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return
        if any(not isinstance(row, dict) or not isinstance(row.get("fs_name"), str) for row in rows):
            return
        existing = {r.name: r for r in records(db, op.cluster_id, "filesystem")}
        found = set()
        for row in rows:
            name = row.get("fs_name") if isinstance(row, dict) else None
            if not isinstance(name, str) or not name or "DELETED" in name:
                continue
            found.add(name)
            metadata = {k: row[k] for k in ("fs_name", "fs_id", "status", "storage_type") if k in row}
            saved = save(db, op, existing.get(name), "filesystem", name, "ready",
                dict(origin="discovered", discovered_at=timestamp, **metadata))
            existing[name] = saved
        for name, saved in existing.items():
            if name not in found:
                saved.state = "deleted"
                saved.revision += 1
    elif op.action == "cache.list":
        groups, members = body(data.get("groups", {})), body(data.get("members", {}))
        rows = members.get("members") if isinstance(members, dict) else None
        names = groups.get("group_names", []) if isinstance(groups, dict) else []
        if not isinstance(rows, list) or not isinstance(names, list):
            return
        existing = records(db, op.cluster_id, "cache")
        owned = {m.get("member_id") for r in existing if r.data.get("origin") != "external"
                 for m in r.data.get("members", [])}
        grouped = {name: [] for name in names if isinstance(name, str) and name}
        for row in rows:
            if not isinstance(row, dict) or not row.get("member_id") or not row.get("group_name"):
                continue
            if row["member_id"] in owned:
                continue
            member = {k: row[k] for k in ("member_id", "group_name", "state", "weight", "cache_size_mb") if k in row}
            member.update(origin="external", listen_ip=row.get("ip"), listen_port=row.get("port"))
            grouped.setdefault(row["group_name"], []).append(member)
        external = {r.name: r for r in existing if r.data.get("origin") == "external"}
        for name, members in grouped.items():
            if not members and any(r.name == name and r.data.get("origin") != "external" for r in existing):
                continue
            previous = external.get(name)
            old = {m["member_id"]: m for m in previous.data.get("members", [])} if previous else {}
            for member in members:
                if old.get(member["member_id"], {}).get("process_state"):
                    member["process_state"] = old[member["member_id"]]["process_state"]
            online = sum(m.get("state") in (1, "1", "CacheGroupMemberStateOnline") for m in members)
            state = "cache_empty" if not members else "running" if online == len(members) else "partial" if online else "stopped"
            save(db, op, previous, "cache", name, state,
                 dict(origin="external", group_name=name, members=members, discovered_at=timestamp))
        # A successful complete MDS listing is authoritative for external groups.
        for name, resource in external.items():
            if name not in grouped:
                resource.state = "deleted"
                resource.revision += 1


def deleted(db, op, work):
    """Keep persisted inventories in step with successful MDS deletions."""
    if work["action"] == "mount.unmount_discovered":
        record = work["record"]
        for resource in records(db, op.cluster_id, "mount"):
            if (resource.id == record.get("saved_resource_id") and resource.name == record["mount_path"]
                    and resource.data.get("machine_id") == work["machine_id"]):
                resource.state = "unmounted"
                resource.revision += 1
        return
    if op.action in ("fs.delete", "fs.delete_batch"):
        name = work["parameters"]["fs_name"]
        for resource in records(db, op.cluster_id, "filesystem"):
            if resource.name == name:
                resource.state = "deleted"
                resource.revision += 1
    elif op.action in ("cache.delete", "cache.delete_batch") and "member_id" in work["parameters"]:
        mid = work["parameters"]["member_id"]
        for resource in records(db, op.cluster_id, "cache"):
            data = deepcopy(resource.data)
            remaining = [m for m in data.get("members", []) if m.get("member_id") != mid]
            if len(remaining) != len(data.get("members", [])):
                data["members"] = remaining
                resource.data = data
                resource.state = "deleted" if not remaining else "partial"
                resource.revision += 1
