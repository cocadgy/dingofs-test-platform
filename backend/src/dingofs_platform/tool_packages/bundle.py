"""Validate administrator-published bundles without executing their contents."""
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

TOOLS = ('dtt', 'dingo', 'dingo-client', 'dingo-cache')


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def safe_file(root, name):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.+/-]+', name):
        raise ValueError('工具包文件名不合法')
    relative = PurePosixPath(name)
    if not name or relative.is_absolute() or '..' in relative.parts:
        raise ValueError('工具包路径不合法')
    target = root / name
    if any(p.is_symlink() for p in [target, *target.parents] if p != root.parent):
        raise ValueError('工具包不能包含符号链接')
    if not target.is_file() or not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('工具包文件不存在或越界')
    return target


def inspect_bundle(base, directory):
    base = Path(base).resolve()
    relative = Path(directory)
    if relative.is_absolute() or '..' in relative.parts or not directory:
        raise ValueError('请选择工具包目录下的相对路径')
    root = base / relative
    if root.is_symlink() or not root.resolve().is_relative_to(base):
        raise ValueError('工具包路径不合法')
    manifest_path = safe_file(root, 'manifest.json')
    if manifest_path.stat().st_size > 65536:
        raise ValueError('工具包清单过大')
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict):
        raise ValueError('工具包清单格式错误')
    tool = manifest.get('tool')
    if tool not in TOOLS or manifest.get('architecture') not in ('x86_64', 'aarch64'):
        raise ValueError('不支持的工具或 CPU 架构')
    if not re.fullmatch(r'[A-Za-z0-9_.+-]{1,80}', manifest.get('version', '')):
        raise ValueError('版本格式错误')
    files = manifest.get('files')
    if not isinstance(files, dict) or not 1 <= len(files) <= 1000:
        raise ValueError('工具包文件清单为空或过大')
    if manifest.get('entrypoint') not in files:
        raise ValueError('缺少入口文件')
    if tool != 'dtt' and manifest.get('entrypoint') != tool:
        raise ValueError('工具入口名必须与工具名一致')
    if tool == 'dtt':
        if manifest.get('entrypoint') == 'dtt':
            raise ValueError('dtt 镜像包入口应命名为 dingofs-testsuite-tool')
        if 'image.tar' not in files or not re.fullmatch(r'sha256:[a-f0-9]{64}', manifest.get('image_id', '')):
            raise ValueError('dtt 工具包必须包含镜像 image.tar 和 image_id')
        if not {'dtt-ai-analyze', 'analysis.schema.json'} <= files.keys():
            raise ValueError('缺少 dtt 配套文件')
    size = 0
    for name, expected in files.items():
        path = safe_file(root, name)
        if not isinstance(expected, str) or not re.fullmatch(r'[a-f0-9]{64}', expected) or sha256_file(path) != expected:
            raise ValueError('工具包文件校验失败：' + name)
        size += path.stat().st_size
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    return {**manifest, 'directory': directory, 'digest': digest, 'size_bytes': size}
