"""Read-only mount discovery. Standalone source is shipped through SSH.

Only proc metadata is read; never stat, list, or traverse a mounted filesystem.
No argv, environment, configuration files, or credentials leave this helper.
"""

import ipaddress
import json
import os
import pwd
import re
import time
from datetime import datetime, timezone
from pathlib import Path


def _scan_read(path, limit):
    with open(path, "rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("扫描元数据超过大小上限")
    return raw.decode("utf-8", errors="replace")


def _scan_endpoints(value):
    result = set()
    for part in value.split(","):
        host, sep, port = part.strip().rpartition(":")
        if not sep or not port.isdigit() or not 1 <= int(port) <= 65535:
            return []
        host = host.strip("[]").lower().rstrip(".")
        try:
            host = str(ipaddress.ip_address(host))
        except ValueError:
            if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", host):
                return []
        result.add(("[" + host + "]" if ":" in host else host) + ":" + str(int(port)))
    return sorted(result)


def _scan_client(argv):
    # Only explicitly understood argument forms are evidence of identity.
    wanted = {"mountpoint", "mount_point", "mount_path", "fsname", "fs_name",
              "mdsaddr", "mds_addr", "mds_addrs"}
    flags = {}
    for i, arg in enumerate(argv[1:], 1):
        key, sep, value = arg.lstrip("-").partition("=")
        if arg.startswith("-") and key in wanted:
            if key in flags:  # conflicting or repeated identity flags are ambiguous
                return None
            flags[key] = value if sep else (argv[i + 1] if i + 1 < len(argv) else "")
    uris = [i for i, arg in enumerate(argv) if arg.startswith("mds://")]
    if uris:
        if len(uris) != 1:
            return None
        i = uris[0]
        addresses, sep, fs = argv[i][6:].partition("/")
        if not sep or i + 1 >= len(argv):
            return None
        return argv[i + 1], fs, _scan_endpoints(addresses)
    paths = {flags[k] for k in ("mountpoint", "mount_point", "mount_path") if k in flags}
    names = {flags[k] for k in ("fsname", "fs_name") if k in flags}
    addresses = {flags[k] for k in ("mdsaddr", "mds_addr", "mds_addrs") if k in flags}
    if len(paths) != 1 or len(names) != 1 or len(addresses) != 1:
        return None
    return paths.pop(), names.pop(), _scan_endpoints(addresses.pop())


def scan_mounts(mds_addr, saved=None, *, proc_root=Path("/proc"), max_mounts=1000):
    started = time.monotonic()
    expected = _scan_endpoints(mds_addr)
    if not expected:
        raise ValueError("当前集群 MDS 地址格式无效，不能确认挂载归属")
    root = Path(proc_root)
    namespace = os.readlink(root / "self/ns/mnt")
    rows, seen = [], set()
    for line in _scan_read(root / "self/mountinfo", 4 * 1024 * 1024).splitlines():
        fields = line.split()
        if "-" not in fields or len(fields) < 10:
            continue
        sep = fields.index("-")
        if sep + 2 >= len(fields) or fields[sep + 1] != "fuse.dingofs":
            continue
        if fields[0] in seen:
            continue
        seen.add(fields[0])
        if len(rows) >= max_mounts:
            raise ValueError("挂载点数量超过扫描上限（1000），本次结果未返回")
        decode = lambda value: re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), value)
        path, source = decode(fields[4]), decode(fields[sep + 2])
        fs = source[8:] if source.startswith("DingoFS:") else ""
        rows.append(dict(mount_id=fields[0], mount_path=path, fs_name=fs,
                         pid=None, client_user=None, mds_addresses=[],
                         cluster_match="unknown", reason="未找到可唯一核验的客户端进程",
                         saved_resource_id=(saved or {}).get(path)))
    candidates = {}
    unreadable = 0
    with os.scandir(root) as entries:
        for index, entry in enumerate(entries):
            if time.monotonic() - started > 30 or index > 200000:
                raise ValueError("扫描耗时或进程数量超过上限，请减少目标机器后重试")
            if not entry.name.isdigit():
                continue
            p = root / entry.name
            try:
                exe = os.path.basename(os.readlink(p / "exe")).removesuffix(" (deleted)")
                if exe not in {"dingo-client", "mount.fuse.dingofs"}:
                    continue
                if os.readlink(p / "ns/mnt") != namespace:
                    continue
                argv = _scan_read(p / "cmdline", 256 * 1024).rstrip("\0").split("\0")
                info = _scan_client(argv)
                if info is None:
                    unreadable += 1
                    continue
                uid = p.stat().st_uid
                try:
                    user = pwd.getpwuid(uid).pw_name
                except KeyError:
                    user = str(uid)
                path, fs, endpoints = info
                candidates.setdefault(path.rstrip("/") or "/", []).append(
                    (int(entry.name), user, fs, endpoints))
            except FileNotFoundError:
                continue  # process exited during scan
            except (PermissionError, OSError, ValueError):
                unreadable += 1
    for row in rows:
        matched = candidates.get(row["mount_path"], [])
        if len(matched) != 1:
            continue
        pid, user, fs, endpoints = matched[0]
        row.update(pid=pid, client_user=user, mds_addresses=endpoints)
        if not endpoints or not fs or fs != row["fs_name"]:
            row["reason"] = "客户端参数缺失或文件系统名称与挂载记录不一致"
        else:
            current = endpoints == expected
            row.update(cluster_match="current" if current else "other",
                       reason="MDS 地址集合一致" if current else "客户端 MDS 地址与当前集群不同")
    data = dict(mounts=rows, scanned_at=datetime.now(timezone.utc).isoformat(),
                namespace=namespace, expected_mds=expected,
                warnings=([f"{unreadable} 个进程信息不可读或参数无法识别，归属可能无法确认"] if unreadable else []))
    if len(json.dumps(data, ensure_ascii=True).encode()) > 1024 * 1024:
        raise ValueError("扫描结果超过大小上限（1 MiB），本次结果未返回")
    return data
