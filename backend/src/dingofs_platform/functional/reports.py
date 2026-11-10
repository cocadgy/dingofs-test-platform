"""Child-scoped report access; no fallback, streaming disclosure or binary attachments."""
import html
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import stat
from urllib.parse import quote, quote_plus

from dingofs_platform.errors import Problem
from dingofs_platform.inventory.permissions import require_manage
from .source_bridge import _BOOTSTRAP, _run_inspector

MAX_REPORT_BYTES = 8 * 1024 * 1024
TEXT_MEDIA = {'.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript',
              '.json': 'application/json', '.txt': 'text/plain', '.xml': 'application/xml',
              '.csv': 'text/csv', '.svg': 'image/svg+xml'}

# No raw EnvironmentConfig crosses the bridge. This private return is consumed
# only by report redaction and never stored in snapshots, logs or HTTP payloads.
_REPORT_SECRETS = _BOOTSTRAP.rsplit('runpy.run_module(', 1)[0] + r'''
import contextlib, io, json
request = json.load(sys.stdin)
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    from src.config.env_parser import parse_environment
    from src.test_runner.functional_redaction import collect_runtime_secrets
    env = parse_environment(request['env_name'], conf_dir=request['source_root'] + '/conf')
    if env is None: raise ValueError('missing environment')
    values = collect_runtime_secrets(env)
print(json.dumps(list(values)))
'''


def load_report_secrets(source_root, env_name, manifest):
    """Fail closed if the exact original code/config version is unavailable."""
    try:
        root = Path(source_root).resolve(strict=True)
        if not manifest or not {'src/test_runner/functional_redaction.py', 'src/config/env_parser.py'} <= manifest.keys():
            raise ValueError('incomplete manifest')
        def verify():
            required = {p.relative_to(root).as_posix() for folder, pattern in (
                ('src', '*.py'), ('conf', '*.yaml'), ('testcases', '*.yaml'), ('template', '*.py'))
                for p in (root / folder).rglob(pattern) if p.is_file()}
            if not required <= manifest.keys():
                raise ValueError('new unpinned source')
            for name, digest in manifest.items():
                if not _relative(name):
                    raise ValueError('unsafe source')
                path = root / name
                if not path.resolve(strict=True).is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ValueError('source changed')
        verify()
        request = json.dumps({'source_root': str(root), 'env_name': env_name}).encode()
        values = json.loads(_run_inspector(root, request, bootstrap=_REPORT_SECRETS))
        verify()
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
            raise ValueError('invalid private credentials')
        return values
    except Exception:
        raise Problem(503, 'report_redaction_unavailable', '原始版本或脱敏凭据不可用，不能下载报告') from None


def _relative(value):
    return (isinstance(value, str) and bool(value) and not PurePosixPath(value).is_absolute()
            and PurePosixPath(value).as_posix() == value and '..' not in PurePosixPath(value).parts
            and '\\' not in value and not any(ord(c) < 32 for c in value))


def report_location(parent, child, actor, path):
    require_manage(actor, parent)
    if (parent.version != 2 or not child or child.run_id != parent.id or not _relative(path)):
        raise Problem(404, 'report_unavailable', '模块报告文件不存在')
    result, identity = child.result or {}, child.remote_identity or {}
    verified = identity.get('remote_state', {}).get('verified_report', {})
    report = result.get('report_path')
    output = identity.get('output')
    root = identity.get('root')
    if (result.get('report_status') != 'ready' or not _relative(report)
            or PurePosixPath(report).name != 'index.html'
            or verified != {'child_id': child.id, 'html_path': report}
            or not isinstance(root, str) or not PurePosixPath(root).is_absolute()
            or PurePosixPath(root).parts[-2:] != ('supervisor', child.id)
            or '..' in PurePosixPath(root).parts
            or not isinstance(output, str) or not PurePosixPath(output).is_absolute()
            or '..' in PurePosixPath(output).parts
            or PurePosixPath(output) != PurePosixPath(root).parent.parent / 'output' / parent.id / child.id):
        raise Problem(404, 'report_unavailable', '模块 HTML 报告尚未验证或不存在')
    return output, report, path


def read_report_file(output, report, relative):
    """Open every path component without symlink following, including output ancestors."""
    if not _relative(report) or not _relative(relative):
        raise Problem(404, 'report_unavailable', '报告文件不存在')
    target = Path(output) / PurePosixPath(report).parent / relative
    if not target.is_absolute() or '..' in target.parts:
        raise Problem(404, 'report_unavailable', '报告文件不存在')
    directory = None
    try:
        directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        for part in target.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        file = os.open(target.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(file, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_REPORT_BYTES:
                raise ValueError('invalid report')
            data = stream.read(MAX_REPORT_BYTES + 1)
            if len(data) > MAX_REPORT_BYTES:
                raise ValueError('oversized report')
            return data
    except (OSError, ValueError):
        raise Problem(404, 'report_unavailable', '报告文件不存在或不能安全读取') from None
    finally:
        if directory is not None:
            os.close(directory)


def report_read_code(output, report, relative):
    import inspect
    return ('import base64,json,os,stat\nfrom pathlib import Path,PurePosixPath\n'
        'class Problem(Exception): pass\nMAX_REPORT_BYTES=' + repr(MAX_REPORT_BYTES) + '\n'
        + inspect.getsource(_relative) + '\n' + inspect.getsource(read_report_file)
        + '\ntry:\n data=read_report_file(' + repr(output) + ',' + repr(report) + ',' + repr(relative) + ')\n'
        + ' print(json.dumps({"data":base64.b64encode(data).decode()}))\n'
        + 'except Exception: print(json.dumps({"missing":True}))\n')


def safe_report_bytes(path, chunks, secrets):
    """Buffer the bounded whole artifact so secrets crossing read boundaries cannot leak."""
    if secrets is None or not isinstance(secrets, (list, tuple)) or any(not isinstance(s, str) for s in secrets):
        raise Problem(503, 'report_redaction_unavailable', '原始版本脱敏凭据不可用，不能下载报告')
    media = TEXT_MEDIA.get(PurePosixPath(path).suffix.lower())
    if not media:
        raise Problem(404, 'report_attachment_withheld', '无法验证安全的附件不提供下载')
    data = bytearray()
    for chunk in chunks:
        data.extend(chunk)
        if len(data) > MAX_REPORT_BYTES:
            raise Problem(404, 'report_unavailable', '报告文件过大')
    try:
        text = data.decode('utf-8', errors='strict')
        if '\x00' in text:
            raise ValueError('binary')
    except (ValueError, UnicodeError):
        raise Problem(404, 'report_attachment_withheld', '非文本附件不提供下载') from None
    variants = set()
    for secret in secrets:
        if secret:
            variants.update((secret, json.dumps(secret, ensure_ascii=False)[1:-1],
                             json.dumps(secret, ensure_ascii=True)[1:-1], quote(secret, safe=''),
                             quote_plus(secret), shlex.quote(secret), html.escape(secret)))
    for value in sorted(variants, key=len, reverse=True):
        text = text.replace(value, '[REDACTED]')
    return text.encode(), media


def download_report(db, actor, run_id, child_id, path):
    import base64
    import time
    from dingofs_platform.functional.models import FunctionalRun, FunctionalModuleRun
    from dingofs_platform.inventory.models import Machine
    from dingofs_platform.inventory.credentials import decrypt_password
    from dingofs_platform.inventory.ssh_transport import SSHConfig
    from dingofs_platform.tool_packages.ssh_session import Remote
    parent = db.get(FunctionalRun, run_id)
    if not parent:
        raise Problem(404, 'not_found', '任务不存在')
    child = db.get(FunctionalModuleRun, child_id)
    output, report, relative = report_location(parent, child, actor, path)
    settings = db.info['functional_settings']
    binding = parent.snapshot.get('runtime_binding', {})
    machine = db.get(Machine, parent.machine_id)
    if not machine or machine.archived:
        raise Problem(503, 'report_machine_unavailable', '原报告机器不可用')
    require_manage(actor, machine)
    if [machine.address, machine.ssh_port, machine.ssh_user] != binding.get('control_connection'):
        raise Problem(409, 'report_machine_changed', '原报告机器连接身份已改变')
    secrets = load_report_secrets(Path(settings.functional_source_root).parent,
        child.environment_snapshot['env_name'], binding.get('functional_runtime', {}).get('source_manifest'))
    # Reject unsupported attachment types before any remote read.
    safe_report_bytes(relative, [], secrets)
    password = decrypt_password(machine.ssh_password_ciphertext, settings.credential_encryption_key)
    config = SSHConfig(machine.address, machine.ssh_port, machine.ssh_user, password)
    code = report_read_code(output, report, relative)
    try:
        transport = db.info.get('functional_report_transport')
        if transport:
            raw = transport(config, code)
        else:
            remote = Remote(config, time.monotonic() + 60, lambda **kw: None, '功能报告')
            try:
                raw = remote.python(code, '读取模块报告', max_bytes=12 * 1024 * 1024)
            finally:
                remote.close()
        if not isinstance(raw, dict) or raw.get('missing') or not isinstance(raw.get('data'), str):
            raise ValueError('missing report')
        data = base64.b64decode(raw['data'], validate=True)
    except Exception:
        raise Problem(404, 'report_unavailable', '报告文件不存在或无法安全读取') from None
    return safe_report_bytes(relative, [data], secrets)
