"""Strict public action parameters and form descriptions.

Remote paths and process identities for existing resources never come from these
parameters: the service resolves them from its own stored resource record.
"""

import copy
import ipaddress
import re


def field(key, label, kind="string", *, required=False, default=None, options=None):
    return {
        "key": key,
        "label": label,
        "type": kind,
        "required": required,
        "default": default,
        "options": options or [],
    }


FS = field("fs_name", "文件系统名称", required=True)
FSID = field("fs_id", "文件系统 ID", "integer", required=True)
PATH = field("path", "文件系统内目录路径", default="/")
RESOURCE = field("resource_id", "资源 ID", required=True)
PROFILE_FIELDS = [
    field("storage_profile_id", "存储配置", default=""),
    field("storage_profile_revision", "存储配置版本", "integer", default=0),
]
PROFILE_KEYS = {f["key"] for f in PROFILE_FIELDS}
CAPACITY = field("capacity", "容量配额（GiB，0 表示不限）", "integer", required=True)
INODES = field("inodes", "inode 配额（0 表示不限）", "integer", required=True)
CLIENT = field("mds_client_path", "MDS 客户端路径", default="dingo-mds-client")
RDMA = [
    field("use_rdma", "使用 RDMA", "boolean", default=False),
    field("rdma_device", "RDMA 设备", default=""),
    field("rdma_port", "RDMA 端口", "integer", default=1),
]
TARGET = [
    field("machine_id", "目标机器", required=True),
    field("target_user", "执行用户", default="dingofs"),
]
MEMBER_FIELDS = (
    TARGET
    + [
        field("member_id", "成员 ID（留空由平台生成）", default=""),
        field("listen_ip", "监听 IP", required=True),
        field("port_mode", "端口分配", default="manual", options=["auto", "manual"]),
        field("listen_port", "监听端口", "integer", default=21000),
        field("cache_dir", "缓存基础目录", required=True),
        field("cache_size_mb", "缓存容量（MiB）", "integer", default=1024),
    ]
    + RDMA
)


def action(name, label, section, mutating, fields):
    return {
        "action": name,
        "label": label,
        "section": section,
        "mutating": mutating,
        "fields": fields,
    }


ACTIONS = [
    action("fs.list", "文件系统列表", "fs", False, []),
    action("fs.get", "文件系统详情", "fs", False, [FS]),
    action(
        "fs.create",
        "创建文件系统",
        "fs",
        True,
        [
            FS,
            field(
                "storage_type",
                "存储类型",
                "select",
                required=True,
                options=["s3", "rados"],
            ),
            field(
                "partition_type",
                "分区类型",
                "select",
                default="hash",
                options=["hash", "monolithic"],
            ),
        ]
        + PROFILE_FIELDS
        + [
            field(
                k,
                label,
                "password" if k in {"s3_ak", "s3_sk", "rados_key"} else "string",
                default="",
            )
            for k, label in [
                ("s3_ak", "S3 Access Key"),
                ("s3_sk", "S3 Secret Key"),
                ("s3_endpoint", "S3 Endpoint"),
                ("s3_bucketname", "S3 Bucket"),
                ("rados_username", "Rados 用户"),
                ("rados_key", "Rados 密钥"),
                ("rados_mon", "Rados Monitor"),
                ("rados_poolname", "Rados Pool"),
                ("rados_clustername", "Rados Cluster"),
            ]
        ],
    ),
    action("fs.delete", "删除文件系统", "fs", True, [FS]),
    action("fs.delete_batch", "通配符批量删除", "fs", True, [field("fs_names", "待删除名单", "names", required=True)]),
    action("quota.fs.get", "查询文件系统配额", "quota", False, [FS]),
    action("quota.fs.set", "设置文件系统配额", "quota", True, [FS, CAPACITY, INODES]),
    action("quota.fs.delete", "清除文件系统配额", "quota", True, [FS]),
    action("quota.dir.get", "查询目录配额", "quota", False, [FS, PATH]),
    action(
        "quota.dir.set", "设置目录配额", "quota", True, [FS, PATH, CAPACITY, INODES]
    ),
    action("quota.dir.delete", "删除目录配额", "quota", True, [FS, PATH]),
    action("trash.get", "查询回收站配置", "trash", False, [FS]),
    action(
        "trash.configure",
        "设置回收站保留天数",
        "trash",
        True,
        [FS, field("trash_days", "保留天数", "integer", required=True), CLIENT],
    ),
    action(
        "trash.restore",
        "恢复回收站",
        "trash",
        True,
        [
            FSID,
            field("hours", "恢复最近小时数（最多 168）", "integer", default=24),
            field("restore_hours_utc", "指定 UTC 小时桶（可选，逗号分隔）", default=""),
            field("put_back", "恢复到原路径", "boolean", default=True),
            field("restore_threads", "恢复线程数", "integer", default=4),
            CLIENT,
        ],
    ),
    action(
        "dirstat.info",
        "目录统计信息",
        "dirstat",
        False,
        [
            FSID,
            PATH,
            field("recursive", "递归", "boolean", default=False),
            field("strict", "严格模式", "boolean", default=False),
            field("raw", "原始数据", "boolean", default=False),
            CLIENT,
        ],
    ),
    action(
        "dirstat.summary",
        "目录统计汇总",
        "dirstat",
        False,
        [
            FSID,
            PATH,
            field("depth", "深度", "integer", default=1),
            field("entries", "条目数", "integer", default=100),
            field("strict", "严格模式", "boolean", default=False),
            CLIENT,
        ],
    ),
    action(
        "dirstat.enable",
        "启用或关闭目录统计",
        "dirstat",
        True,
        [FS, field("enable", "启用", "boolean", default=True), CLIENT],
    ),
    action(
        "dirstat.sync",
        "同步目录统计",
        "dirstat",
        True,
        [
            FSID,
            PATH,
            field("recursive", "递归", "boolean", default=False),
            field("repair", "修复", "boolean", default=False),
            CLIENT,
        ],
    ),
    action("cache.leave", "成员离开缓存组", "cache", True, [field("member_id", "成员 UUID", required=True), field("group_name", "当前缓存组", required=True)]),
    action("cache.unlock", "解锁成员", "cache", True, [field("member_id", "成员 UUID", required=True), field("group_name", "当前缓存组（未分组留空）", default="")]),
    action("cache.weight", "设置成员权重", "cache", True, [field("member_id", "成员 UUID", required=True), field("group_name", "当前缓存组（未分组留空）", default=""), field("weight", "权重", "integer", default=100)]),
    action("cache.list", "缓存组与成员列表", "cache", False, []),
    action(
        "cache.create",
        "创建缓存组",
        "cache",
        True,
        [
            field("group_name", "缓存组名称", required=True),
            field("count", "每份成员配置创建数量", "integer", default=1),
            field("cache_profile_id", "缓存组配置", default=""),
            field("cache_profile_revision", "缓存组配置版本", "integer", default=0),
            field("cache_options", "缓存参数", "cache_options", default={}),
            field("members", "缓存成员", "members", required=True),
        ],
    ),
    action("cache.stop", "停止缓存组", "cache", True, [RESOURCE]),
    action("cache.delete", "删除缓存组成员登记", "cache", True, [field("member_id", "缓存组成员", required=True)]),
    action("cache.delete_batch", "通配符批量删除缓存成员", "cache", True, [field("member_ids", "待删除成员", "names", required=True)]),
    action(
        "mount.create",
        "挂载文件系统",
        "mount",
        True,
        TARGET
        + [
            FS,
            field("mount_path", "挂载路径", required=True),
            field("count", "挂载数量", "integer", default=1),
            field("subdir", "挂载子目录", default=""),
            field("cache_group", "缓存组名称", default=""),
            field("mount_profile_id", "挂载配置", default=""),
            field("mount_profile_revision", "挂载配置版本", "integer", default=0),
            field("mount_options", "客户端参数", "mount_options", default={}),
        ]
        + RDMA,
    ),
    action("mount.unmount", "卸载文件系统", "mount", True, [RESOURCE]),
    action("mount.delete", "删除已卸载客户端记录", "mount", True, [RESOURCE]),
    action("mount.remount", "重新挂载文件系统", "mount", True, [RESOURCE]),
    action(
        "mount.logs",
        "客户端日志",
        "mount",
        False,
        [
            RESOURCE,
            field("filename", "日志文件名（留空列出文件）", default=""),
            field("lines", "最近行数", "integer", default=500),
        ],
    ),
    action("mount.status", "检查挂载状态", "mount", False, [RESOURCE]),
]
ACTIONS.append(action("cache.plan", "检查缓存成员端口", "cache", False,
    copy.deepcopy(next(item for item in ACTIONS if item["action"] == "cache.create")["fields"])))
INDEX = {item["action"]: item for item in ACTIONS}


def catalog():
    result = copy.deepcopy(ACTIONS)
    for item in result:
        if item["section"] in {"fs", "quota", "trash", "dirstat"}:
            item["section"] = "filesystem"
        for f in item["fields"]:
            f["type"] = {"string": "text", "integer": "number"}.get(
                f["type"], f["type"]
            )
            if f["key"] == "members":
                f["fields"] = copy.deepcopy(MEMBER_FIELDS)
                for member_field in f["fields"]:
                    member_field["type"] = {"string": "text", "integer": "number"}.get(
                        member_field["type"], member_field["type"]
                    )
    return result


def _string(key, value):
    if (
        not isinstance(value, str)
        or len(value) > 4096
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError(f"{key}: invalid string")
    if (
        key
        in {
            "fs_name",
            "group_name",
            "cache_group",
            "machine_id",
            "resource_id",
            "member_id",
            "storage_profile_id",
            "rdma_device",
        }
        and value
        and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", value)
    ):
        raise ValueError(f"{key}: invalid name")
    if key == "restore_hours_utc" and value:
        buckets = value.split(",")
        if not 1 <= len(buckets) <= 169 or any(
            not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{2}", bucket)
            for bucket in buckets
        ) or len(buckets) != len(set(buckets)):
            raise ValueError("restore_hours_utc: invalid UTC hour buckets")
        from datetime import datetime
        try:
            for bucket in buckets:
                datetime.strptime(bucket, "%Y-%m-%d-%H")
        except ValueError:
            raise ValueError("restore_hours_utc: invalid UTC hour buckets") from None
    if key == "target_user" and not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", value):
        raise ValueError("target_user: invalid account")
    if key in {"path", "mount_path", "cache_dir", "subdir"} and value:
        if (
            not value.startswith("/")
            or "//" in value
            or any(part in {".", ".."} for part in value.split("/"))
        ):
            raise ValueError(f"{key}: requires an absolute normalized path")
        if key in {"mount_path", "cache_dir"} and (
            value == "/"
            or value.rstrip("/")
            in {
                "/tmp",
                "/home",
                "/mnt",
                "/etc",
                "/proc",
                "/sys",
                "/dev",
                "/run",
                "/var",
                "/usr",
                "/bin",
                "/sbin",
                "/lib",
                "/lib64",
            }
            or value.startswith(
                (
                    "/etc/",
                    "/proc/",
                    "/sys/",
                    "/dev/",
                    "/usr/",
                    "/bin/",
                    "/sbin/",
                    "/lib/",
                    "/lib64/",
                )
            )
        ):
            raise ValueError(f"{key}: choose a dedicated data directory")
    if (
        key == "filename"
        and value
        and (value in {".", ".."} or "/" in value or len(value.encode()) > 255)
    ):
        raise ValueError("filename: requires a basename")
    if key == "listen_ip":
        try:
            ipaddress.ip_address(value)
        except ValueError:
            raise ValueError("listen_ip: invalid IP address") from None
    if (
        key == "mds_client_path"
        and value != "dingo-mds-client"
        and (
            not re.fullmatch(r"/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+", value)
            or any(p in {".", ".."} for p in value.split("/"))
        )
    ):
        raise ValueError("mds_client_path: requires an absolute executable path")
    if key == "cache_dir" and any(c in value for c in ",:"):
        raise ValueError(
            "cache_dir: provide one directory without multidisk delimiters"
        )
    if key in {"path", "mount_path", "cache_dir", "subdir"} and value and value != "/":
        value = value.rstrip("/")
    return value


def _fields(specs, parameters):
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")  # noqa: TRY004 - public validation contract
    allowed = {f["key"] for f in specs}
    unknown = parameters.keys() - allowed
    if unknown:
        raise ValueError("unknown parameters: " + ", ".join(sorted(unknown)))
    result = {}
    for f in specs:
        key = f["key"]
        value = parameters.get(key, copy.deepcopy(f["default"]))
        if value is None or (f["required"] and value == ""):
            raise ValueError(f"{key}: required")
        if f["type"] == "integer":
            if key == "count":
                if type(value) is not int or value < 1:
                    raise ValueError("count: 数量必须为正整数")
                result[key] = value
                continue
            if (
                key == "lines"
                and isinstance(value, str)
                and re.fullmatch(r"[0-9]{1,4}", value)
            ):
                value = int(value)
            limits = {
                "weight": (0, 2**32 - 1),
                "listen_port": (1, 65535),
                "rdma_port": (1, 255),
                "cache_size_mb": (1, 2**32 - 1),
                "lines": (1, 1000),
                "hours": (1, 168),
                "restore_threads": (1, 128),
                "depth": (0, 100),
                "entries": (1, 10000),
                "cache_expire_s": (1, 2**32 - 1),
                "trash_days": (0, 36500),
            }
            low, high = limits.get(key, (0, 2**63 - 1))
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{key}: requires an integer in [{low}, {high}]")
        elif f["type"] == "mount_options":
            from dingofs_platform.mount_profiles.catalog import validate_options
            value = validate_options(value)
        elif f["type"] == "cache_options":
            from dingofs_platform.cache_profiles.catalog import validate_options
            value = validate_options(value)
        elif f["type"] == "boolean":
            if type(value) is not bool:
                raise ValueError(f"{key}: requires a boolean")
        elif f["type"] == "names":
            if not isinstance(value, list) or not value or (key == "fs_names" and len(value) > 100):
                raise ValueError(f"{key}: provide a nonempty list of names" + (" (maximum 100)" if key == "fs_names" else ""))
            value = [_string("member_id" if key == "member_ids" else "fs_name", name) for name in value]
            if not all(value) or len(value) != len(set(value)):
                raise ValueError(f"{key}: empty or duplicate name")
        elif f["type"] == "members":
            if not isinstance(value, list) or not value:
                raise ValueError("members: provide at least one member")
            value = [_fields(MEMBER_FIELDS, member) for member in value]
            ids = [v["member_id"] for v in value if v.get("member_id")]
            if len(ids) != len(set(ids)):
                raise ValueError("member_id: 每个成员必须使用不同 ID，或留空自动生成")
            if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", mid) for mid in ids):
                raise ValueError("member_id: 无效成员 ID")
            endpoints = [(v["machine_id"], v["listen_ip"], v["listen_port"]) for v in value if v["port_mode"] == "manual"]
            if len(endpoints) != len(set(endpoints)):
                raise ValueError("members: duplicate listen endpoint")
        else:
            value = _string(key, value)
            if f["options"] and value not in f["options"]:
                raise ValueError(f"{key}: invalid option")
        result[key] = value
    if result.get("use_rdma") and not result.get("rdma_device"):
        raise ValueError("rdma_device: required when RDMA is enabled")
    return result


def validate(action_name, parameters):
    if action_name not in INDEX:
        raise ValueError("unknown resource action")
    if action_name == "cache.create" and isinstance(parameters, dict) and "plan_id" in parameters:
        result = _fields([field("plan_id", "检查清单", required=True)], parameters)
        import uuid
        result["plan_id"] = str(uuid.UUID(result["plan_id"]))
        return result
    if action_name == "cache.stop" and isinstance(parameters, dict) and "member_ids" in parameters:
        result = _fields([field("member_ids", "待停止成员", "names", required=True), field("force", "强制停止", "boolean", default=False)], parameters)
        if not result["force"]: result.pop("force")
        return result
    if action_name in ("mount.unmount", "mount.delete") and isinstance(parameters, dict) and "resource_ids" in parameters:
        return _fields([field("resource_ids", "客户端名单", "names", required=True)], parameters)
    specs = INDEX[action_name]["fields"]
    if action_name == "cache.delete" and isinstance(parameters, dict) and "resource_id" in parameters:
        # Existing saved operations still describe a managed group lifecycle.
        # Keep them replayable, but never accept both target kinds at once.
        return _fields([RESOURCE], parameters)
    if action_name == "fs.create":
        if isinstance(parameters, dict) and parameters.keys() & PROFILE_KEYS:
            # Connection settings belong to the selected profile; reject every
            # caller override, including empty fields from stale clients.
            specs = [f for f in specs if f["key"] in PROFILE_KEYS | {"fs_name", "partition_type"}]
            result = _fields(specs, parameters)
            if not result["storage_profile_id"] or result["storage_profile_revision"] < 1:
                raise ValueError("storage profile and revision required")
            return result
        specs = [f for f in specs if f["key"] not in PROFILE_KEYS]
    result = _fields(specs, parameters)
    if action_name in ("cache.create", "cache.plan"):
        from .bulk_create import validate_cache_count
        validate_cache_count(result["members"], result.get("count", 1))
    if action_name == "mount.create" and result.get("count", 1) > 1:
        # Validate the longest generated pathname without expanding the batch.
        _string("mount_path", result["mount_path"].rstrip("/") + f'-{result["count"]:03d}')
    if result.get("count") == 1:
        result.pop("count", None)
    if action_name == "mount.create" and bool(result.get("mount_profile_id")) != bool(result.get("mount_profile_revision")):
        raise ValueError("mount profile and revision required together")
    if action_name in ("cache.create", "cache.plan"):
        if bool(result["cache_profile_id"]) != bool(result["cache_profile_revision"]):
            raise ValueError("cache_profile_id: 配置与版本必须同时提供")
        result["cache_expire_s"] = int(result["cache_options"].get("cache_expire_s", "259200"))
    if action_name == "fs.create":
        keys = (
            ["s3_ak", "s3_sk", "s3_endpoint", "s3_bucketname"]
            if result["storage_type"] == "s3"
            else [
                "rados_username",
                "rados_key",
                "rados_mon",
                "rados_poolname",
                "rados_clustername",
            ]
        )
        for key in keys:
            if not result[key]:
                raise ValueError(f"{key}: required for {result['storage_type']}")
    return result
