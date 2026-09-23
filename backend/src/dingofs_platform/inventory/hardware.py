"""Fixed, read-only Linux probes and defensive output parsing (no remote Python)."""

import ipaddress
import json
import re
from .ssh_transport import execute

COMMANDS = {
    "cpu": "lscpu -J",
    "memory": "cat /proc/meminfo",
    "disks": "lsblk -b -J -o NAME,TYPE,SIZE,MODEL,ROTA",
    "filesystems": "df -P -k -l",
    "mounts": "cat /proc/self/mountinfo",
    "interfaces": "ip -j address show",
    "speeds": """for p in /sys/class/net/*; do [ -e "$p" ] || continue; v=$(cat "$p/speed" 2>/dev/null) || v=unknown; printf '%s\\t%s\\n' "${p##*/}" "$v"; done""",
    "rdma": """[ -d /sys/class/infiniband ] || exit 0
for d in /sys/class/infiniband/*; do
  [ -d "$d" ] || continue
  for p in "$d"/ports/*; do
    [ -d "$p" ] || continue
    names=$(for n in "$p"/gid_attrs/ndevs/*; do [ -f "$n" ] && cat "$n" 2>/dev/null; done | sort -u | tr '\\n' ',')
    printf '%s\\t%s\\t%s\\n' "${d##*/}" "${p##*/}" "$names"
  done
done""",
}


def number(value, maximum=2**63 - 1):
    if isinstance(value, bool) or not re.fullmatch(r"\d{1,20}", str(value)):
        raise ValueError("invalid number")
    result = int(value)
    if result > maximum:
        raise ValueError("number out of range")
    return result


def short(value, limit=512):
    if (
        not isinstance(value, str)
        or len(value) > limit
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("invalid text")
    return value


def document(text, kind):
    value = json.loads(text)
    if not isinstance(value, kind):
        raise ValueError("invalid document")
    return value


def cpu(text):
    fields = {}

    def visit(rows):
        if not isinstance(rows, list):
            raise ValueError("invalid CPU rows")
        for row in rows:
            fields[short(row["field"]).rstrip(":")] = row.get("data")
            if "children" in row:
                visit(row["children"])

    visit(document(text, dict)["lscpu"])
    logical = number(fields["CPU(s)"], 1048576)
    if not logical:
        raise ValueError("invalid CPU count")
    physical = None
    if not fields.get("Hypervisor vendor"):
        try:
            physical = number(fields["Socket(s)"], 65536) * number(
                fields["Core(s) per socket"], 65536
            )
            if not 0 < physical <= logical:
                physical = None
        except (KeyError, ValueError):
            pass
    model = fields.get("Model name")
    return {
        "model": short(model) if model else None,
        "logical_cores": logical,
        "physical_cores": physical,
    }


def memory(text):
    m = re.search(r"^MemTotal:\s+(\d+)\s+kB\s*$", text, re.M)
    if not m:
        raise ValueError("missing memory")
    size = number(m[1], 2**53) * 1024
    if not size:
        raise ValueError("invalid memory")
    return {"total_bytes": size}


def disks(text):
    rows = []
    seen = set()

    def visit(nodes, depth=0):
        if not isinstance(nodes, list) or depth > 32:
            raise ValueError("invalid device tree")
        for d in nodes:
            name = short(d["name"])
            kind = short(d["type"])
            if name not in seen:
                seen.add(name)
                rotation = d.get("rota")
                rows.append(
                    {
                        "name": name,
                        "type": kind,
                        "size_bytes": number(d["size"]),
                        "model": short(d["model"]) if d.get("model") else None,
                        "rotational": rotation in (True, 1, "1")
                        if rotation is not None
                        else None,
                    }
                )
            if len(rows) > 4096:
                raise ValueError("too many devices")
            if "children" in d:
                visit(d["children"], depth + 1)

    visit(document(text, dict)["blockdevices"])
    return rows


def unescape_mount(value):
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), value)


def filesystems(text, mount_text):
    mount_ids = {}
    for line in mount_text.splitlines():
        parts = line.split()
        if len(parts) >= 10 and "-" in parts:
            mount_ids[unescape_mount(parts[4])] = parts[2]
    rows = []
    seen = {}
    for line in text.splitlines()[1:]:
        if not line.strip():
            continue
        match = re.fullmatch(
            r"(.+?)\s+(\d+)\s+(\d+)\s+(\d+)\s+\S+%\s+(.+)", line.strip()
        )
        if not match:
            raise ValueError("invalid df row")
        source = short(match[1])
        target = short(match[5], 4096)
        identity = mount_ids.get(target, source)
        rows.append(
            {
                "source": source,
                "mountpoint": target,
                "total_bytes": number(match[2], 2**53) * 1024,
                "available_bytes": number(match[4], 2**53) * 1024,
                "same_filesystem_as": seen.get(identity),
            }
        )
        seen.setdefault(identity, target)
    return rows


def interfaces(text, speed_text):
    speeds = {}
    for line in speed_text.splitlines():
        parts = line.split("\t")
        if len(parts) == 2:
            try:
                speeds[parts[0]] = number(parts[1], 10**9) or None
            except ValueError:
                speeds[parts[0]] = None
    rows = []
    for item in document(text, list):
        name = short(item["ifname"])
        addresses = []
        for addr in item.get("addr_info", []):
            if addr.get("family") not in ("inet", "inet6"):
                continue
            ip = ipaddress.ip_address(addr["local"])
            addresses.append(f"{ip}/{number(addr['prefixlen'], ip.max_prefixlen)}")
        rows.append(
            {
                "name": name,
                "mac": short(item["address"]) if item.get("address") else None,
                "addresses": addresses,
                "state": short(item.get("operstate", "UNKNOWN")),
                "mtu": number(item["mtu"], 2**32),
                "speed_mbps": speeds.get(name),
            }
        )
    return rows


def rdma(text):
    rows = []
    for line in text.splitlines():
        if not line:
            continue
        device, port, names = line.split("\t")
        rows.append(
            {
                "device": short(device),
                "port": number(port, 65535),
                "interfaces": [short(n) for n in names.split(",") if n],
            }
        )
    return rows


def parse_hardware(results):
    warnings = []

    def output(name):
        value = results.get(name)
        if not value or value.returncode != 0 or len(value.stdout.encode()) > 1048576:
            raise ValueError("missing output")
        return value.stdout

    info = {"schema_version": 1}
    parsers = {
        "cpu": lambda: cpu(output("cpu")),
        "memory": lambda: memory(output("memory")),
        "disks": lambda: disks(output("disks")),
        "filesystems": lambda: filesystems(output("filesystems"), output("mounts")),
        "interfaces": lambda: interfaces(
            output("interfaces"),
            results.get("speeds").stdout
            if results.get("speeds") and results["speeds"].returncode == 0
            else "",
        ),
        "rdma": lambda: rdma(output("rdma")),
    }
    for name, parse in parsers.items():
        try:
            info[name] = parse()
        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            IndexError,
            RecursionError,
        ):
            info[name] = None
            warnings.append(name + ": 信息不可用或输出格式无法识别")
    if info["cpu"] and (
        info["cpu"]["physical_cores"] is None or info["cpu"]["model"] is None
    ):
        warnings.append("cpu: 物理核数或型号未知")
    if info["interfaces"] and any(
        i["speed_mbps"] is None and i["name"] != "lo" for i in info["interfaces"]
    ):
        warnings.append("interfaces: 部分网卡速率未知")
    info["warnings"] = warnings
    return info


def collect(config, transport=execute, timeout_s=30):
    info = parse_hardware(
        transport(config, COMMANDS, timeout_s=timeout_s, max_bytes=1048576)
    )
    available = any(
        info[k] for k in ("cpu", "memory", "disks", "filesystems", "interfaces")
    )
    status = ("partial" if info["warnings"] else "success") if available else "failed"
    return {"status": status, "hardware_info": info, "warnings": info["warnings"]}
