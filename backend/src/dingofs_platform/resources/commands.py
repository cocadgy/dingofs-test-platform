"""Fixed Dingo command builders; no public parameter is interpreted as shell."""

import json
import shlex
from pathlib import Path

from . import schemas
from .schemas import INDEX, validate


def catalog():
    return schemas.catalog()


def secret_keys(action):
    return {"s3_ak", "s3_sk", "rados_key"} if action == "fs.create" else set()


def is_mutating(action):
    if action not in INDEX:
        raise ValueError("unknown resource action")
    return INDEX[action]["mutating"]


def _simple_commands(action, p, mds):
    addr = ["--mdsaddr", mds]
    json_flags = ["--format", "json"]
    if action == "fs.list":
        return [["dingo", "fs", "list", *addr, *json_flags]]
    if action in {"fs.get", "trash.get"}:
        return [["dingo", "fs", "query", "--fsname", p["fs_name"], *addr, *json_flags]]
    if action == "fs.create":
        argv = [
            "dingo",
            "fs",
            "create",
            p["fs_name"],
            "--storagetype",
            p["storage_type"],
        ]
        keys = (
            ["s3_ak", "s3_sk", "s3_endpoint", "s3_bucketname"]
            if p["storage_type"] == "s3"
            else [
                "rados_username",
                "rados_key",
                "rados_mon",
                "rados_poolname",
                "rados_clustername",
            ]
        )
        for key in keys:
            argv.extend(["--" + key.replace("_", ".", 1), p[key]])
        return [[*argv, *addr, "--partitiontype", p["partition_type"], *json_flags]]
    if action == "fs.delete":
        return [
            ["dingo", "fs", "delete", p["fs_name"], *addr, "--noconfirm", *json_flags]
        ]
    if action.startswith("quota."):
        _, scope, operation = action.split(".")
        argv = [
            "dingo",
            "fs",
            "config" if scope == "fs" else "quota",
            "set" if scope == "fs" and operation == "delete" else operation,
            "--fsname",
            p["fs_name"],
        ]
        if scope == "dir":
            argv += ["--path", p["path"]]
        if operation == "set" or scope == "fs" and operation == "delete":
            argv += [
                "--capacity",
                str(p.get("capacity", 0)),
                "--inodes",
                str(p.get("inodes", 0)),
            ]
        argv += addr
        if scope == "dir":
            argv += ["--rpcretrytimes", "100"]
        return [argv]
    if action == "cache.list":
        return [
            ["dingo", "cache", scope, "list", *addr, *json_flags]
            for scope in ("group", "member")
        ]
    client = [p.get("mds_client_path", "dingo-mds-client"), "--mds_addr=" + mds]
    if action == "trash.configure":
        return [
            [
                *client,
                "--cmd=updatefstrashdays",
                "--fs_name=" + p["fs_name"],
                "--trash_days=" + str(p["trash_days"]),
            ]
        ]
    if action == "trash.restore":
        return [
            [
                *client,
                "--cmd=restoretrash",
                "--fs_id=" + str(p["fs_id"]),
                "--hours=" + str(p["hours"]),
                "--put_back=" + str(p["put_back"]).lower(),
                "--restore_threads=" + str(p["restore_threads"]),
            ]
        ]
    if action == "dirstat.enable":
        return [
            [
                *client,
                "--cmd=UpdateFsEnableDirStats",
                "--fs_name=" + p["fs_name"],
                "--enable_dir_stats=" + str(p["enable"]).lower(),
            ]
        ]
    if action.startswith("dirstat."):
        verb = action.split(".")[1]
        argv = [
            *client,
            "--cmd=" + ("syncdirstat" if verb == "sync" else verb),
            "--fs_id=" + str(p["fs_id"]),
            "--path=" + p["path"],
        ]
        argv.extend(
            "--" + key for key in ("recursive", "strict", "raw", "repair") if p.get(key)
        )
        if verb == "summary":
            argv += ["--depth=" + str(p["depth"]), "--entries=" + str(p["entries"])]
        return [argv]
    return []


def build_script(action, parameters, mds_addr, resource_id, record=None):
    if (
        not isinstance(mds_addr, str)
        or not mds_addr
        or len(mds_addr) > 4096
        or any(ord(c) < 32 for c in mds_addr)
    ):
        raise ValueError("invalid cluster MDS address")
    if action == "cache.stop_external":
        p = validate("cache.delete", parameters)
        if "member_id" not in p or not isinstance(record, dict) or record.get("member_id") != p["member_id"]:
            raise ValueError("server-owned external member record is required")
    elif action in ("cache.wait_offline", "cache.verify_members"):
        # Internal read-only phase; never exposed in the public catalog.
        p = validate("cache.stop", parameters)
        if "member_ids" not in p:
            raise ValueError("member IDs required for offline check")
    elif action in ("cache.create", "cache.plan") and record is not None and "members" not in parameters:
        # This is the service-owned, already validated member expansion.
        public_member = {
            k: parameters[k]
            for k in (
                "member_id",
                "machine_id",
                "target_user",
                "listen_ip",
                "listen_port",
                "port_mode",
                "cache_dir",
                "cache_size_mb",
                "use_rdma",
                "rdma_device",
                "rdma_port",
            )
            if k in parameters
        }
        normalized = validate(
            action,
            {
                "group_name": parameters["group_name"],
                "members": [public_member],
            },
        )
        p = dict(
            normalized["members"][0],
            group_name=normalized["group_name"],
            cache_expire_s=normalized["cache_expire_s"],
        )
    else:
        p = validate(action, parameters)
    lifecycle = action.startswith("mount.") or action in {
        "cache.create",
        "cache.plan",
        "cache.stop",
    } or (action == "cache.delete" and "resource_id" in p)
    if lifecycle and (
        not isinstance(record, dict)
        or not record.get("state_dir")
        or not record.get("log_dir")
    ):
        raise ValueError("server-owned resource record is required")
    req = {
        "action": action,
        "parameters": p,
        "mds_addr": mds_addr,
        "resource_id": str(resource_id),
        "record": record or {},
        "commands": _simple_commands(action, p, mds_addr),
    }
    source = Path(__file__).with_name("remote_helper.py").read_text(encoding="utf-8")
    return (
        "python3 -c "
        + shlex.quote(source)
        + " "
        + shlex.quote(json.dumps(req, ensure_ascii=True))
    )
