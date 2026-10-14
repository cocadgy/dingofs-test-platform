import json
import os
import platform
import shutil
import subprocess
from pathlib import Path


def check(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=20)
        return result.returncode, (result.stdout + result.stderr)[:16000]
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


root = Path.home() / '.local/share/dingofs-platform/tools'
items = []
for tool in ('dtt', 'dingo', 'dingo-client', 'dingo-cache'):
    managed = root / tool / 'current' / tool
    existing = shutil.which(tool)
    path = str(managed) if managed.is_file() else existing
    if not path:
        # Dingo components often aren't added to PATH.
        candidates = sorted((Path.home() / '.dingo/components' / tool).glob('*/' + tool))
        path = str(candidates[-1]) if candidates else None
    record = {'tool': tool, 'path': path, 'status': 'missing', 'version': '', 'details': ''}
    if path:
        rc, details = check([path, '--help'])
        record.update(status='ready' if help_succeeded(tool, rc, details) else 'unavailable', details=details)
        if managed.is_file():
            try:
                record['version'] = json.loads((managed.parent / 'manifest.json').read_text())['version']
            except (OSError, ValueError, KeyError):
                pass
    if tool == 'dtt' and path:
        rc, configured = check([path, 'config', 'show'])
        config = {}
        for line in configured.splitlines():
            key, sep, value = line.strip().partition(':')
            if sep and key in ('runtime', 'image'):
                config[key] = value.strip()
        runtime_name = config.get('runtime', 'docker')
        runtime = shutil.which(runtime_name) if runtime_name in ('docker','podman') else None
        image = config.get('image', '')
        if rc or not image or image.startswith('-'):
            record.update(status='unavailable', details='无法读取 dtt 镜像配置，请重新部署工具包')
        elif not runtime:
            record.update(status='unavailable', details='缺少 Docker/Podman，请先安装并启动容器运行环境')
        else:
            rc, details = check([runtime, 'info'])
            if rc:
                record.update(status='unavailable', details='容器运行环境不可用：' + details)
            else:
                record['details'] = '镜像：' + image
                for command in ([runtime, 'image', 'inspect', image],
                                [runtime, 'run', '--rm', '--pull=never', '--network=none', '--entrypoint', 'fio', image, '--version'],
                                [runtime, 'run', '--rm', '--pull=never', '--network=none', '--entrypoint', 'elbencho', image, '--version']):
                    rc, details = check(command)
                    if rc:
                        record.update(status='unavailable', details='dtt 镜像或内置工具不可用：' + details)
                        break
    if path and not record['version'] and tool != 'dtt':
        rc, version = check([path, '--version'])
        if rc in (0,1) and len(version.strip().splitlines()) == 1:
            record['version'] = version.strip()[:200]
    items.append(record)
print(json.dumps({'architecture': platform.machine(), 'user': os.environ.get('USER', ''), 'items': items}))
