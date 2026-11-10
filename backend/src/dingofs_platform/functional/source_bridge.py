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


def _run_inspector(root: Path, request: bytes) -> bytes:
    """Drain both pipes incrementally; kill/reap on timeout or either I/O limit."""
    deadline = time.monotonic() + INSPECT_TIMEOUT_SECONDS
    output = bytearray()
    total = 0
    try:
        with subprocess.Popen(
            [sys.executable, '-I', '-B', '-c', _BOOTSTRAP, str(root)],
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
