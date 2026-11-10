"""Bounded, read-only JSON bridge to an administrator-trusted framework checkout.

``source_root`` is server configuration/caller authority, never request data. The
child restrictions limit accidental side effects; they do not make arbitrary
untrusted Python safe. No framework module is imported into the API process.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import selectors
import subprocess
import sys
import time

from pydantic import ValidationError

from .contracts import EnvironmentDescriptor

INSPECT_TIMEOUT_SECONDS = 10
MAX_OUTPUT_BYTES = 1024 * 1024
MAX_REQUEST_BYTES = 64 * 1024

# -I ignores PYTHONPATH/user site; -B prevents bytecode writes. Install the audit
# guard before importing any framework code, including package initializers.
_BOOTSTRAP = r'''
import os, resource, runpy, sys
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
def guard(event, args):
    if event.startswith(('socket.', 'subprocess.', 'ctypes.')) or event in {
        'os.system', 'os.exec', 'os.posix_spawn', 'os.fork', 'os.forkpty',
        'os.remove', 'os.rename', 'os.rmdir', 'os.mkdir', 'os.link', 'os.symlink',
        'os.chmod', 'os.chown', 'os.truncate', 'os.utime',
    }:
        raise PermissionError('inspection side effect denied')
    if event == 'open':
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        ):
            raise PermissionError('inspection write denied')
sys.addaudithook(guard)
sys.path.insert(0, sys.argv[1])
runpy.run_module('src.test_runner.functional_contracts', run_name='__main__')
'''


def _relative(value: str) -> bool:
    return (isinstance(value, str) and bool(value) and '\\' not in value
            and not any(c in value for c in '\x00\r\n')
            and not PurePosixPath(value).is_absolute()
            and '..' not in PurePosixPath(value).parts)


def _run_inspector(root: Path, request: bytes, *, bootstrap: str = _BOOTSTRAP) -> bytes:
    """Drain both pipes incrementally; kill/reap on timeout or either I/O limit."""
    deadline = time.monotonic() + INSPECT_TIMEOUT_SECONDS
    output = bytearray()
    total = 0
    try:
        with subprocess.Popen(
            [sys.executable, '-I', '-B', '-c', bootstrap, str(root)],
            cwd=root, env={'PATH': os.defpath, 'LANG': 'C.UTF-8'},
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ) as process:
            try:
                with selectors.DefaultSelector() as selector:
                    for stream in (process.stdin, process.stdout, process.stderr):
                        os.set_blocking(stream.fileno(), False)
                    selector.register(process.stdin, selectors.EVENT_WRITE)
                    selector.register(process.stdout, selectors.EVENT_READ)
                    selector.register(process.stderr, selectors.EVENT_READ)
                    sent = 0
                    while selector.get_map():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise ValueError('source inspector timed out')
                        for key, _ in selector.select(remaining):
                            if key.fileobj is process.stdin:
                                try:
                                    sent += os.write(key.fd, request[sent:])
                                except BrokenPipeError:
                                    sent = len(request)
                                if sent == len(request):
                                    selector.unregister(key.fileobj)
                                    key.fileobj.close()
                                continue
                            chunk = os.read(key.fd, min(65536, MAX_OUTPUT_BYTES + 1))
                            if not chunk:
                                selector.unregister(key.fileobj)
                                continue
                            total += len(chunk)
                            if total > MAX_OUTPUT_BYTES:
                                raise ValueError('source inspector output limit exceeded')
                            if key.fileobj is process.stdout:
                                output.extend(chunk)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError('source inspector timed out')
                if process.wait(timeout=remaining):
                    raise ValueError('source inspector failed')
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
    except subprocess.TimeoutExpired:
        raise ValueError('source inspector timed out') from None
    except OSError:
        raise ValueError('source inspector failed') from None
    return bytes(output)


def inspect_source(source_root: Path, env_name: str, modules: dict[str, list[str]]) -> EnvironmentDescriptor:
    """Return the pure framework descriptor; all exceptions are safe to display."""
    if (not isinstance(env_name, str) or not env_name or len(env_name) > 512
            or any(c in env_name for c in '\x00\r\n') or not isinstance(modules, dict)
            or not all(_relative(module) and isinstance(cases, list)
                       and all(_relative(case) for case in cases)
                       for module, cases in modules.items())):
        raise ValueError('invalid inspection request')
    try:
        supplied = Path(source_root)
        if '..' in supplied.parts or supplied.is_symlink():
            raise ValueError
        root = supplied.resolve(strict=True)
        entry = root / 'src/test_runner/functional_contracts.py'
        if not root.is_dir() or not entry.is_file():
            raise ValueError
        # Validate imported source paths too, not just YAML handled by inspector.
        if not (root / 'src').resolve().is_relative_to(root):
            raise ValueError
        for path in (root / 'src').rglob('*'):
            if path.is_symlink() and not path.resolve().is_relative_to(root):
                raise ValueError
    except (OSError, RuntimeError, TypeError, ValueError):
        raise ValueError('trusted source inspector is unavailable') from None
    request = json.dumps({'source_root': str(root), 'env_name': env_name, 'modules': modules}).encode()
    if len(request) > MAX_REQUEST_BYTES:
        raise ValueError('inspection request limit exceeded')
    output = _run_inspector(root, request)
    try:
        if len(output) > MAX_OUTPUT_BYTES:
            raise ValueError
        descriptor = EnvironmentDescriptor.model_validate_json(output, strict=True)
        if descriptor.env_name != env_name or set(descriptor.modules) != set(modules):
            raise ValueError
        manifest = descriptor.source_manifest
        expected = sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if descriptor.digest != expected:
            raise ValueError
        for relative, digest in manifest.items():
            if not _relative(relative):
                raise ValueError
            path = root / relative
            if not path.resolve().is_relative_to(root) or sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError
    except (OSError, RuntimeError, TypeError, ValueError, ValidationError):
        raise ValueError('invalid inspector response') from None
    return descriptor


# Reuse the exact parser and guard, emitting only explicit allowlisted scalars.
# Expanded cache entries retain their source count and per-host running index.
# Consume contiguous blocks; equality never merges independent source groups.
_PROJECTION = _BOOTSTRAP.rsplit("runpy.run_module(", 1)[0] + r'''
import json, re, hmac
from dataclasses import asdict
from src.config.env_parser import parse_environment
from src.config.command_utils import parse_run_as_user
request = json.load(sys.stdin)
env = parse_environment(request['env_name'], conf_dir=request['source_root'] + '/conf')
if env is None: raise ValueError('missing environment')
user, secret = parse_run_as_user(env.run_as_user)
sensitive = [env.run_as_user.partition('/')[2], secret]
if env.storage and env.storage.s3: sensitive.extend((env.storage.s3.s3_ak, env.storage.s3.s3_sk))
if env.storage and env.storage.rados: sensitive.append(env.storage.rados.rados_key)
sensitive = [value for value in sensitive if value]
omitted = False
def flags(raw):
    global omitted
    result = {}
    for key, value in raw.items():
        if (not isinstance(key, str) or not re.fullmatch(r'--[A-Za-z][A-Za-z0-9_]*', key)
            or key == '--mds_addrs' or re.search(r'(^|_)(password|secret|token|credential|key|ak|sk)(_|$)', key[2:].lower())
            or type(value) not in (str, int, bool)
            or isinstance(value, str) and (len(value) > 2048 or any(c in value for c in '\r\n\x00;|&$`')
                                          or any(secret in value for secret in sensitive))):
            omitted = True
        else: result[key] = value
    return result
clients = [{'machine_id': '', 'client_count': c.client_count,
            'mount_path': c.mount_path or '/tmp/dingofs-functional',
            'fs_name': c.fs_name or 'platform-test', 'client_conf': flags(c.client_conf)} for c in env.clients]
caches = []
position = 0
indices = {}
while position < len(env.remote_caches):
    first = env.remote_caches[position]
    count = first.remote_cache_count
    if type(count) is not int or not 1 <= count <= 1000: raise ValueError('invalid cache group')
    block = env.remote_caches[position:position + count]
    start = indices.get(first.host, 0)
    if len(block) != count or any(asdict(c) != asdict(first) or c._index != start + i for i,c in enumerate(block)):
        raise ValueError('ambiguous cache expansion')
    indices[first.host] = start + count
    caches.append({'machine_id': '', 'remote_cache_count': count, 'remote_cache_conf': flags(first.remote_cache_conf)})
    position += count
storage = env.storage
storage_ready = bool(storage and (
    storage.storage_type == 's3' and storage.s3 and all((storage.s3.s3_ak, storage.s3.s3_sk, storage.s3.s3_endpoint, storage.s3.s3_bucketname))
    or storage.storage_type == 'rados' and storage.rados and all((storage.rados.rados_username, storage.rados.rados_key, storage.rados.rados_mon, storage.rados.rados_poolname))))
execution = {'user': user, 'declared_ssh_user': env.ssh_user,
    'source_auth_present': bool(secret or env.ssh_identity_file), 'storage_ready': storage_ready,
    'authentication_mode': 'key' if env.ssh_identity_file else ('password' if secret else 'missing'),
    'authentication_matches': bool(not env.ssh_identity_file and secret and request.get('authentication') and all(
        item['user'] == user and hmac.compare_digest(item['value'].encode(), secret.encode())
        for item in request.get('authentication', []))),
    'command_host': env.host or env.mds_addr.split(',')[0].rsplit(':', 1)[0],
    'mds_node_count': env.mds_node_count,
    'dingo': env.dingo_tool_path or '/usr/local/bin/dingo',
    'clients': [{'host': c.host, 'fs_name': c.fs_name, 'mount_path': c.mount_path,
                 'binary': c.client_bin_path, 'count': c.client_count,
                 'dingo': c.dingo_tool_path or env.dingo_tool_path or '/usr/local/bin/dingo',
                 'upgrade_binary': c.smooth_upgrade_target_client_binary or env.smooth_upgrade_target_client_binary,
                 'paths': [p for p in [c.client_conf.get('--cache_dir', ''), c.client_conf.get('--log_dir', ''), *c.client_cache_dirs] if p],
                 'port': int(c.client_conf.get('--vfs_dummy_server_port', 11000))} for c in env.clients],
    'caches': [{'host': c.host, 'binary': c.cache_bin_path, 'dingo': c.dingo_tool_path or '/usr/local/bin/dingo',
                'paths': [p for p in [c.remote_cache_conf.get('--cache_dir', ''), c.remote_cache_conf.get('--log_dir', ''), *c.remote_cache_dirs] if p],
                'port': int(c.remote_cache_conf.get('--listen_port', 8000))} for c in env.remote_caches]}
result = json.dumps({'version': 1, 'settings': {'mount_root': clients[0]['mount_path'] if clients else '/tmp/dingofs-functional',
    'fs_prefix': clients[0]['fs_name'] if clients else 'platform-test', 'clients': clients, 'remote_caches': caches, 'binaries': {}},
    'execution': execution, 'omitted': omitted})
if any(secret in result for secret in sensitive): raise ValueError('unsafe projection value')
print(result)
'''


def project_source(source_root: Path, env_name: str, *, authentication: list[dict] | None = None) -> dict:
    """Secret-free portable settings and per-host prerequisites from one parser.

    Never expose the raw resolved YAML or parser object to the API process.
    Source is rehashed across both inspections to refuse concurrent drift.
    """
    before = inspect_source(source_root, env_name, {})
    if before.issues:
        raise ValueError('environment projection is unavailable')
    root = Path(source_root).resolve(strict=True)
    request = json.dumps({'source_root': str(root), 'env_name': env_name, 'authentication': authentication}).encode()
    if len(request) > MAX_REQUEST_BYTES:
        raise ValueError('inspection request limit exceeded')
    try:
        value = json.loads(_run_inspector(root, request, bootstrap=_PROJECTION))
        from .environments.service import validate_settings
        # Validate with temporary rebinding; public copies intentionally have no machine IDs.
        settings = value['settings']
        rebound = {**settings, **{key: [{**item, 'machine_id': 'unbound'} for item in settings[key]]
                                for key in ('clients', 'remote_caches')}}
        if not settings['clients']:
            rebound.pop('clients')
        validate_settings(rebound)
        execution = value['execution']
        if (value.keys() != {'version', 'settings', 'execution', 'omitted'} or value['version'] != 1
                or type(value['omitted']) is not bool
                or execution.keys() != {'user', 'declared_ssh_user', 'source_auth_present', 'authentication_mode', 'authentication_matches', 'storage_ready',
                                        'command_host', 'mds_node_count', 'dingo', 'clients', 'caches'}
                or not all(isinstance(execution[k], str) for k in ('user', 'declared_ssh_user', 'command_host', 'dingo'))
                or type(execution['mds_node_count']) is not int
                or not all(type(execution[k]) is bool for k in ('source_auth_present', 'authentication_matches', 'storage_ready'))):
            raise ValueError
        if execution['authentication_mode'] not in ('password', 'key', 'missing'):
            raise ValueError
        for kind in ('clients', 'caches'):
            for item in execution[kind]:
                expected = {'host', 'binary', 'dingo', 'paths', 'port'} | ({'fs_name', 'mount_path', 'count', 'upgrade_binary'} if kind == 'clients' else set())
                if (item.keys() != expected or not all(isinstance(item[k], str) for k in expected - {'paths', 'port', 'count'})
                        or not isinstance(item['paths'], list) or not all(isinstance(p, str) for p in item['paths'])
                        or type(item['port']) is not int or not 1 <= item['port'] <= 65535
                        or kind == 'clients' and (type(item['count']) is not int or not 1 <= item['count'] <= 1000)):
                    raise ValueError
        if inspect_source(root, env_name, {}).digest != before.digest:
            raise ValueError
    except Exception:
        raise ValueError('invalid environment projection') from None
    return {**value, 'source_manifest': before.source_manifest, 'digest': before.digest}
