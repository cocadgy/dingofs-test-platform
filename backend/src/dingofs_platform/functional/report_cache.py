"""Atomic private snapshots. Wire: {'bundle': base64(uncompressed USTAR)}.

Limits: 8 MiB/file, 64 MiB/tree, 4096 entries, depth 32, 128 MiB tar.
Capacity counts 4 KiB allocations including directories and ready metadata.
256 stable lock stripes coordinate each key across processes without unbounded
lock-file accumulation; keys sharing a stripe also serialize. Never unlink locks.
"""
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import inspect
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import tempfile

from dingofs_platform.errors import Problem
from .reports import MAX_REPORT_BYTES, _relative, read_report_file

MAX_TREE_BYTES = 64 * 1024 * 1024
MAX_TREE_FILES = 4096
MAX_BUNDLE_BYTES = 128 * 1024 * 1024
MAX_WIRE_BYTES = ((MAX_BUNDLE_BYTES + 2) // 3) * 4 + 1024


def _safe_name(name):
    return _relative(name) and name != '.' and len(name) <= 1024 and len(PurePosixPath(name).parts) <= 32


def _remote_bundle(output, report):
    """Descriptor-relative traversal refuses links, including all ancestors."""
    target = Path(output) / PurePosixPath(report).parent
    if not target.is_absolute() or '..' in target.parts or not _relative(report):
        raise ValueError('unsafe path')
    directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in target.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        stream = io.BytesIO()
        total, count = 0, 0
        with tarfile.open(fileobj=stream, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            def visit(fd, prefix=''):
                nonlocal total, count
                with os.scandir(fd) as entries:
                    for entry in entries:
                        name = prefix + entry.name
                        count += 1
                        if count > MAX_TREE_FILES or not _safe_name(name):
                            raise ValueError('tree limit')
                        info = entry.stat(follow_symlinks=False)
                        if stat.S_ISDIR(info.st_mode):
                            sub = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                            try:
                                item = tarfile.TarInfo(name)
                                item.type = tarfile.DIRTYPE
                                archive.addfile(item)
                                visit(sub, name + '/')
                            finally:
                                os.close(sub)
                        elif stat.S_ISREG(info.st_mode):
                            file = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                            with os.fdopen(file, 'rb') as source:
                                before = os.fstat(source.fileno())
                                if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_REPORT_BYTES:
                                    raise ValueError('file limit')
                                data = source.read(MAX_REPORT_BYTES + 1)
                                after = os.fstat(source.fileno())
                                total += len(data)
                                if (len(data) > MAX_REPORT_BYTES or total > MAX_TREE_BYTES
                                        or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)):
                                    raise ValueError('changed or oversized file')
                                item = tarfile.TarInfo(name)
                                item.size = len(data)
                                archive.addfile(item, io.BytesIO(data))
                        else:
                            raise ValueError('unsafe file')
                        if stream.tell() > MAX_BUNDLE_BYTES:
                            raise ValueError('bundle limit')
            visit(directory)
        if stream.tell() > MAX_BUNDLE_BYTES:
            raise ValueError('bundle limit')
        return {'bundle': base64.b64encode(stream.getvalue()).decode('ascii')}
    finally:
        os.close(directory)


def report_bundle_code(output, report):
    return ('import base64,io,json,os,stat,tarfile\nfrom pathlib import Path,PurePosixPath\n'
        + '\n'.join(f'{name}={value!r}' for name, value in {
            'MAX_REPORT_BYTES': MAX_REPORT_BYTES, 'MAX_TREE_BYTES': MAX_TREE_BYTES,
            'MAX_TREE_FILES': MAX_TREE_FILES, 'MAX_BUNDLE_BYTES': MAX_BUNDLE_BYTES}.items()) + '\n'
        + inspect.getsource(_relative) + '\n' + inspect.getsource(_safe_name) + '\n'
        + inspect.getsource(_remote_bundle) + '\ntry:\n print(json.dumps(_remote_bundle('
        + repr(output) + ',' + repr(report) + ')))\n'
        + 'except Exception: print(json.dumps({"error":"unsafe_report"}))\n')


def cache_key(run_id, child_id, output, report, connection):
    return hashlib.sha256(json.dumps([run_id, child_id, output, report, connection], separators=(',', ':')).encode()).hexdigest()


def _private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise Problem(503, 'report_cache_unavailable', '报告缓存目录必须由服务独占且权限为 0700')


@contextmanager
def _lock(path, *, blocking=True):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        yield
    finally:
        os.close(fd)


def _decode_bundle(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get('bundle'), str) or len(raw['bundle']) > MAX_WIRE_BYTES:
        raise ValueError('invalid bundle')
    data = base64.b64decode(raw['bundle'], validate=True)
    if len(data) > MAX_BUNDLE_BYTES or len(data) % 512 or len(data) < 1024 or data[-1024:] != b'\0' * 1024:
        raise ValueError('oversized or incomplete bundle')
    files, directories, names, total = {}, set(), set(), 0
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
        for member in archive:
            name = member.name
            if (not _safe_name(name) or name in names or len(names) >= MAX_TREE_FILES
                    or member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE) or member.pax_headers
                    or member.size < 0 or member.size > MAX_REPORT_BYTES):
                raise ValueError('unsafe archive entry')
            names.add(name)
            if member.isdir():
                directories.add(name)
            else:
                total += member.size
                if total > MAX_TREE_BYTES:
                    raise ValueError('tree limit')
                files[name] = archive.extractfile(member).read(MAX_REPORT_BYTES + 1)
                if len(files[name]) != member.size:
                    raise ValueError('truncated entry')
            directories.update(p.as_posix() for p in PurePosixPath(name).parents if p.as_posix() != '.')
        if any(data[archive.offset:]):
            raise ValueError('unexpected bytes after archive')
    if 'index.html' not in files or directories & files.keys():
        raise ValueError('missing index or conflicting paths')
    cost = 4096 * (3 + len(directories)) + sum(max(4096, ((len(v) + 4095) // 4096) * 4096) for v in files.values())
    return files, directories, cost


def _make_room(root, limit, cost, current):
    entries = []
    for entry in root.iterdir():
        if len(entry.name) != 64 or any(c not in '0123456789abcdef' for c in entry.name):
            continue
        if entry.is_symlink():
            raise ValueError('unsafe cache entry')
        metadata = json.loads(read_report_file(str(entry), 'ready.json', 'ready.json'))
        entries.append((entry.stat().st_mtime_ns, entry, metadata['cost']))
    total = sum(item[2] for item in entries)
    for _, entry, size in sorted(entries):
        if total + cost <= limit:
            break
        if entry.name == current:
            continue
        if entry.name[:2] == current[:2]:
            # Caller already holds this stripe exclusively, including this victim.
            shutil.rmtree(entry)
            total -= size
            continue
        try:
            with _lock(root / 'locks' / entry.name[:2], blocking=False):
                shutil.rmtree(entry)
                total -= size
        except BlockingIOError:
            continue
    if total + cost > limit:
        raise Problem(503, 'report_cache_capacity', '报告超过缓存容量或缓存正在使用，请稍后重试')


def cached_report(root, limit, key, relative, fetch):
    """Caller authorizes each request; reads remain locked against eviction."""
    if not _safe_name(relative):
        raise Problem(404, 'report_unavailable', '报告文件路径无效')
    root = Path(root)
    if len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
        raise ValueError('invalid cache key')
    try:
        _private_directory(root)
        _private_directory(root / 'locks')
        with _lock(root / 'locks' / key[:2]):
            entry = root / key
            if not entry.exists():
                files, directories, cost = _decode_bundle(fetch())
                if cost > limit:
                    raise Problem(503, 'report_cache_capacity', '报告大小超过本地缓存容量')
                with _lock(root / 'capacity.lock'):
                    # Staging is created only under this lock, so leftovers are dead writers.
                    for stale in root.glob('.staging-*'):
                        if not stale.is_symlink() and stale.is_dir():
                            shutil.rmtree(stale)
                    _make_room(root, limit, cost, key)
                    stage = Path(tempfile.mkdtemp(prefix='.staging-', dir=root))
                    try:
                        content = stage / 'content'
                        content.mkdir(mode=0o700)
                        for directory in sorted(directories, key=lambda name: len(PurePosixPath(name).parts)):
                            (content / directory).mkdir(mode=0o700, exist_ok=True)
                        for name, data in files.items():
                            with os.fdopen(os.open(content / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as target:
                                target.write(data)
                        with os.fdopen(os.open(stage / 'ready.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as target:
                            json.dump({'cost': cost}, target)
                        os.rename(stage, entry)
                    finally:
                        if stage.exists():
                            shutil.rmtree(stage)
            data = read_report_file(str(entry / 'content'), 'index.html', relative)
            os.utime(entry, None, follow_symlinks=False)
            return data
    except Problem:
        raise
    except (OSError, ValueError, TypeError, KeyError, tarfile.TarError):
        raise Problem(503, 'report_cache_unavailable', '模块报告缓存读取失败，报告可能不完整、过大或包含不安全文件；请重试') from None
