"""Small, read-only Linux resource sample for the dashboard SSH probe."""

import json
import math
import shlex

# Keep collection on the target host. Only local block-backed filesystems are
# sampled, so an unavailable network mount cannot stall the dashboard scan.
SAMPLE_SCRIPT = r'''
import json, os, time

def cpu():
    with open('/proc/stat') as f:
        fields = [int(v) for v in f.readline().split()[1:]]
    return sum(fields), fields[3] + (fields[4] if len(fields) > 4 else 0)

start_total, start_idle = cpu()
time.sleep(0.2)
end_total, end_idle = cpu()
whole = end_total - start_total
cpu_percent = round(100 * (1 - (end_idle - start_idle) / whole), 1) if whole > 0 else None
with open('/proc/meminfo') as f:
    mem = {parts[0].rstrip(':'): int(parts[1]) * 1024
           for line in f if (parts := line.split()) and len(parts) >= 2}
mem_total = mem['MemTotal']
mem_used = max(0, mem_total - mem['MemAvailable'])

local = {'ext2', 'ext3', 'ext4', 'xfs', 'btrfs', 'zfs'}
seen = {}
disks = []
with open('/proc/self/mountinfo') as f:
    mounts = list(f)
for line in sorted(mounts, key=lambda value: value.split()[4]):
    fields = line.split()
    if '-' not in fields:
        continue
    split = fields.index('-')
    key, mountpoint, kind, device = fields[2], fields[4], fields[split + 1], fields[split + 2]
    if kind not in local:
        continue
    mountpoint = (mountpoint.replace('\\040', ' ').replace('\\011', '\t')
                            .replace('\\012', '\n').replace('\\134', '\\'))
    if key in seen:
        seen[key]['mountpoints'].append(mountpoint)
        continue
    try:
        stat = os.statvfs(mountpoint)
    except OSError:
        continue
    total = stat.f_blocks * stat.f_frsize
    used = (stat.f_blocks - stat.f_bfree) * stat.f_frsize
    if total > 0:
        disk = {'mountpoint': mountpoint, 'mountpoints': [mountpoint], 'device': device,
                      'used_bytes': used, 'total_bytes': total,
                'percent': round(used * 100 / total, 2)}
        disks.append(disk)
        seen[key] = disk
print(json.dumps({'cpu_percent': cpu_percent, 'memory_used_bytes': mem_used,
                  'memory_total_bytes': mem_total, 'disks': disks}, separators=(',', ':')))
'''
SAMPLE_COMMAND = "python3 -c " + shlex.quote(SAMPLE_SCRIPT)


def parse_usage(raw):
    try:
        value = json.loads(raw)
        cpu = value["cpu_percent"]
        memory_used = value["memory_used_bytes"]
        memory_total = value["memory_total_bytes"]
        disks = value["disks"]
        if cpu is not None and (not isinstance(cpu, (int, float)) or not math.isfinite(cpu) or not 0 <= cpu <= 100):
            raise ValueError
        if any(isinstance(item, bool) or not isinstance(item, int) for item in (memory_used, memory_total)):
            raise ValueError
        if not 0 <= memory_used <= memory_total or memory_total == 0 or not isinstance(disks, list):
            raise ValueError
        for disk in disks:
            if not isinstance(disk, dict) or any(not isinstance(disk.get(key), str) for key in ("mountpoint", "device")):
                raise ValueError
            paths = disk.get("mountpoints")
            if paths is not None and (not isinstance(paths, list) or not paths
                                     or any(not isinstance(path, str) for path in paths)):
                raise ValueError
            used, total, percent = disk["used_bytes"], disk["total_bytes"], disk["percent"]
            if (isinstance(used, bool) or isinstance(total, bool)
                    or not isinstance(used, int) or not isinstance(total, int)
                    or not 0 <= used <= total or total == 0
                    or isinstance(percent, bool) or not isinstance(percent, (int, float))
                    or not math.isfinite(percent) or not 0 <= percent <= 100):
                raise ValueError
        return value
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError("invalid_metrics") from exc
