"""Read-only existing-environment preflight and short-lived, source-bound tokens.

The caller supplies settings through db.info and owns the transaction. Transport
is injectable at the SSH boundary only. No installation or container execution
is permitted here. Task10 must call validate_preflight at submit and revalidate
the returned pinned binding immediately before queued launch.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import secrets
import shlex

from pydantic import BaseModel, Field
from sqlalchemy import select

from dingofs_platform.auth.models import User
from dingofs_platform.auth.users import lock_accounts
from dingofs_platform.errors import Problem
from dingofs_platform.inventory.credentials import decrypt_password
from dingofs_platform.inventory.host_identity import normalize_host
from dingofs_platform.inventory.models import Cluster, Machine
from dingofs_platform.inventory.permissions import require_manage
from dingofs_platform.inventory.ssh_transport import SSHConfig, execute
from dingofs_platform.operations.leases import check_conflicts, functional_requests
from dingofs_platform.resources.external_cache import machine_addresses
from dingofs_platform.tool_packages.models import ToolJob
from .catalog import MODULE_DIRS, catalogue
from .contracts import EnvironmentDescriptor
from .environments.models import FunctionalEnvironmentProfile as Profile
from .models import FunctionalPreflight
from .schemas import RunSpec
from .source_bridge import inspect_source, project_source
from .submission import NormalizedSubmission, _digest, normalize_submission

FEATURES = {'exact_case_plan_v1', 'runtime_context_v1', 'owned_cleanup_v1',
            'lifecycle_events_v2', 'cancel_boundary_v1', 'inspection_v1'}
PROBE_CHECKS = ('identity', 'tools', 'binaries', 'directories', 'ports', 'proc',
                'pidfd', 'fuse_cleanup', 'filesystem_schema', 'mount_identity')


class PreflightResult(BaseModel):
    can_start: bool
    token: str | None = Field(default=None, repr=False)
    expires_at: datetime | None = None
    checks: list[dict]
    required_confirmations: list[str] = Field(default_factory=list)
    impacts: list[dict] = Field(default_factory=list)


# Only read files, enumerate identity and invoke fixed read-only query argv.
# Exceptions produce booleans, never raw remote output or environment data.
READ_ONLY_PROBE = r'''
import hashlib, json, os, pathlib, pwd, re, shutil, signal, stat, subprocess, sys
r = json.loads(sys.argv[1])
checks = {k: True for k in ('identity','tools','binaries','directories','ports','proc','pidfd','fuse_cleanup','filesystem_schema','mount_identity')}
user = pwd.getpwuid(os.geteuid()).pw_name
checks['identity'] = user == r['user']
def query(argv):
    value = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    if value.returncode not in (0, 1) or len(value.stdout) + len(value.stderr) > 1024 * 1024:
        raise ValueError('query failed')
    return value
def parent_safe(value):
    p = pathlib.Path(value)
    if not p.is_absolute() or '..' in p.parts or str(p) == '/': return False
    for ancestor in [p, *p.parents]:
        if ancestor.is_symlink(): return False
    parent = p if p.exists() else p.parent
    return parent.is_dir() and os.access(parent, os.W_OK | os.X_OK)
checks['tools'] = all(shutil.which(tool) for tool in r['tools'])
checks['binaries'] = all(pathlib.Path(p).is_file() and os.access(p, os.X_OK) for p in r['binaries'])
checks['directories'] = all(parent_safe(p) for p in r['paths'])
try:
    pathlib.Path('/proc/self/stat').read_text()
    pathlib.Path('/proc/self/mountinfo').read_text()
    processes = []
    for p in pathlib.Path('/proc').iterdir():
        if not p.name.isdigit(): continue
        try:
            comm = (p / 'comm').read_text().strip()
            if comm not in ('dingo-client', 'dingo-cache'): continue
            exe = os.readlink(p / 'exe')
            argv = (p / 'cmdline').read_bytes().decode().rstrip('\0').split('\0')
            before = (p / 'stat').read_text().rsplit(')', 1)[1].split()
            start = before[19]
            after = (p / 'stat').read_text().rsplit(')', 1)[1].split()
            if pathlib.Path(exe).name != comm or not start.isdigit() or start != after[19] or after[0] == 'Z': raise ValueError('identity')
            processes.append((comm, argv))
        except FileNotFoundError: continue
except Exception: checks['proc'] = False; processes = []
if r['cache']:
    checks['pidfd'] = hasattr(os, 'pidfd_open') and hasattr(signal, 'pidfd_send_signal')
    if checks['pidfd']:
        try: os.close(os.pidfd_open(os.getpid()))
        except Exception: checks['pidfd'] = False
if r['client']:
    try:
        if os.geteuid() == 0:
            status = pathlib.Path('/proc/self/status').read_text()
            checks['fuse_cleanup'] = bool(int(re.search(r'^CapEff:\s+([0-9a-f]+)', status, re.M)[1], 16) & (1 << 21))
        else:
            helper = pathlib.Path('/usr/bin/fusermount3')
            checks['fuse_cleanup'] = helper.is_file() and os.access(helper, os.X_OK) and helper.stat().st_uid == 0 and bool(helper.stat().st_mode & stat.S_ISUID)
    except Exception: checks['fuse_cleanup'] = False
try:
    occupied = set()
    for filename in ('/proc/net/tcp', '/proc/net/tcp6'):
        for line in pathlib.Path(filename).read_text().splitlines()[1:]:
            fields = line.split()
            if fields[3] == '0A': occupied.add(int(fields[1].rsplit(':', 1)[1], 16))
    for port in r['ports']:
        if not any(p not in occupied for p in range(port, min(port + 1000, 65536))): checks['ports'] = False
except Exception: checks['ports'] = False
if r['fs_query']:
    try:
        answer = query(r['fs_query'])
        if answer.returncode: raise ValueError('query failed')
        data = json.loads(answer.stdout)
        found = []
        def visit(v):
            if isinstance(v, dict):
                name = next((v[k] for k in ('fs_name','fsname','fsName') if k in v), None)
                if name is not None:
                    ident = next((v[k] for k in ('fs_id','fsId','id') if k in v), None)
                    if not isinstance(name, str) or not name or type(ident) is bool or not str(ident).isdigit(): raise ValueError('schema')
                    found.append((name, str(ident)))
                for child in v.values(): visit(child)
            elif isinstance(v, list):
                for child in v: visit(child)
        visit(data)
        checks['filesystem_schema'] = bool(found) and len({n for n,i in found}) == len(found) and set(r.get('fixed_names', [])) <= {n for n,i in found}
    except Exception: checks['filesystem_schema'] = False
if r['mount_roots']:
    try:
        answer = query(['findmnt', '--json', '--output', 'ID,TARGET,SOURCE,FSTYPE'])
        if answer.returncode: raise ValueError('findmnt')
        def walk(items):
            for mount in items:
                yield mount
                yield from walk(mount.get('children', []))
        mounts = list(walk(json.loads(answer.stdout)['filesystems']))
        for mount in mounts:
            target = mount['target']
            if not any(target == p or target.startswith(p.rstrip('/') + '/') for p in r['mount_roots']): continue
            source = mount['source']
            if not str(mount.get('id', '')).isdigit() or mount['fstype'] not in ('fuse.dingofs', 'fuse.dingo'): raise ValueError('mount identity')
            if source.startswith('DingoFS:'): fs = source[len('DingoFS:'):]
            elif source.startswith('mds://' + r['mds'] + '/'): fs = source.rsplit('/', 1)[1]
            else: raise ValueError('mount source')
            matches = []
            for comm, argv in processes:
                if comm != 'dingo-client': continue
                opts = {}
                for i,arg in enumerate(argv):
                    if arg.startswith('--'):
                        key, sep, val = arg.partition('=')
                        opts.setdefault(key, []).append(val if sep else (argv[i+1] if i+1 < len(argv) else ''))
                names = opts.get('--fs_name', []) + opts.get('--fsname', [])
                addresses = opts.get('--mds_addr', []) + opts.get('--mdsaddr', [])
                paths = opts.get('--mountpoint', []) + opts.get('--mount_point', [])
                if not paths:
                    paths = [a for i,a in enumerate(argv[1:], 1) if a == target and (i == 1 or not argv[i-1].startswith('-') or '=' in argv[i-1])]
                for arg in argv[1:]:
                    if arg.startswith('mds://'):
                        address, sep, name = arg[6:].rpartition('/')
                        names.append(name); addresses.append(address)
                if set(names) == {fs} and set(addresses) == {r['mds']} and paths == [target]: matches.append(argv)
            if len(matches) != 1: raise ValueError('client identity')
    except Exception: checks['mount_identity'] = False
observations = {'user': user, 'uid': os.geteuid(), 'binaries': {}, 'parents': {}}
try:
    files = set(r['binaries']) | {shutil.which(tool) for tool in r['tools'] if shutil.which(tool)}
    if r['client'] and os.geteuid() != 0: files.add('/usr/bin/fusermount3')
    for filename in sorted(files):
        digest = hashlib.sha256()
        with open(filename, 'rb') as stream:
            while True:
                chunk = stream.read(65536)
                if not chunk: break
                digest.update(chunk)
        observations['binaries'][filename] = digest.hexdigest()
except Exception: checks['binaries'] = False
try:
    for value in r['paths']:
        path = pathlib.Path(value)
        parent = path if path.exists() else path.parent
        identity = parent.stat()
        observations['parents'][value] = [identity.st_dev, identity.st_ino]
except Exception: checks['directories'] = False
fingerprint = hashlib.sha256(json.dumps(observations, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
print(json.dumps({'user': user, 'checks': checks, 'fingerprint': fingerprint}))
'''


def _settings(db):
    value = db.info.get('functional_settings')
    if value is None:
        raise Problem(503, 'preflight_unconfigured', '预检服务未配置')
    return value


def resolve_submission(db, actor, payload: RunSpec) -> NormalizedSubmission:
    """Resolve fresh descriptors; never accept client-supplied environment data."""
    root = Path(_settings(db).functional_source_root)
    try:
        catalog = catalogue(root)
    except (OSError, ValueError):
        raise Problem(422, 'source_unavailable', '可信用例源不可用') from None
    environments = {}
    grouped = {}
    for plan in payload.module_plans:
        grouped.setdefault(plan.environment_profile_id, {})[plan.module] = [
            f'testcases/{MODULE_DIRS[plan.module]}/{case}' for case in plan.cases]
    for profile_id, modules in grouped.items():
        row = db.get(Profile, profile_id, populate_existing=True)
        if not row or row.deleted or not row.enabled:
            raise Problem(422, 'environment_unavailable', '测试环境不可用或为基础模板')
        if row.source_kind != 'predefined':
            raise Problem(422, 'unsupported_environment', '引导预检需要现有预置环境')
        try:
            base = inspect_source(root.parent, row.source_key, {})
            descriptor = inspect_source(root.parent, row.source_key, modules)
        except ValueError:
            raise Problem(422, 'source_unavailable', '可信环境源不可用') from None
        if base.digest != row.source_digest:
            raise Problem(409, 'environment_source_changed', '预置环境源已改变，请同步后重新预检')
        environments[profile_id] = {'id': profile_id, 'revision': row.revision, **descriptor.model_dump(mode='json')}
    return normalize_submission(payload, catalog, environments)


def _target(db, actor, host):
    host = normalize_host(host)
    matches = [m for m in db.scalars(select(Machine).where(Machine.archived == False))
               if host in machine_addresses(m) or host == m.name]
    if len(matches) != 1 or matches[0].maintenance:
        raise Problem(422, 'target_unresolved', '所有测试目标必须唯一绑定可用的已登记机器')
    require_manage(actor, matches[0])
    return matches[0]


def _transport(db, machine, user, argv):
    # Framework direct execution identities cannot be proven by a successful
    # unrelated login account. Support only explicit same-account credentials.
    if user != machine.ssh_user or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', user):
        raise Problem(422, 'authentication_unsupported', '执行用户与登记 SSH 用户不同，无法验证实际执行身份')
    if not machine.ssh_password_ciphertext:
        raise Problem(422, 'credentials_missing', '测试目标未配置 SSH 凭据')
    injected = db.info.get('functional_preflight_transport')
    settings = _settings(db)
    try:
        if injected:
            return injected(machine, user, argv)
        config = SSHConfig(machine.address, machine.ssh_port, user,
                           decrypt_password(machine.ssh_password_ciphertext, settings.credential_encryption_key))
        result = execute(config, {'probe': shlex.join(argv)}, timeout_s=60, max_bytes=1024 * 1024)['probe']
        if result.returncode:
            raise ValueError
        return json.loads(result.stdout)
    except Exception:
        raise Problem(422, 'remote_probe_failed', '只读检查失败，请核验 SSH 身份和工具配置') from None


def _capability(value):
    if (not isinstance(value, dict) or type(value.get('version')) is not int or value.get('version') != 2
            or not isinstance(value.get('features'), list)
            or not all(isinstance(s, str) for s in value['features'])
            or not FEATURES <= set(value['features'])
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', value.get('image_id', ''))):
        raise ValueError('runtime capability')
    for key in ('files', 'source_manifest'):
        manifest = value.get(key)
        if not isinstance(manifest, dict) or not manifest:
            raise ValueError('runtime manifest')
        for name, digest in manifest.items():
            path = PurePosixPath(name)
            if (not name or path.is_absolute() or '..' in path.parts or '\\' in name or any(ord(c) < 32 for c in name)
                    or path.as_posix() != name or not re.fullmatch(r'[0-9a-f]{64}', digest)):
                raise ValueError('runtime manifest')
    return {key: value[key] for key in ('version', 'features', 'files', 'image_id', 'source_manifest')}


def _binding(db, control, pinned=None):
    jobs = db.scalars(select(ToolJob).where(ToolJob.machine_id == control.id, ToolJob.state == 'success',
                      ToolJob.action.in_(('install', 'auto_install'))).order_by(ToolJob.created_at.desc()))
    for job in jobs:
        result = job.result or {}
        if pinned and job.id != pinned.get('job_id'):
            continue
        path = result.get('immutable_path', '')
        if (not isinstance(path, str) or not path.startswith('/') or PurePosixPath(path).name != 'dtt'
                or any(part in PurePosixPath(path).parts for part in ('..', 'current', 'latest'))
                or any(ord(c) < 32 for c in path) or result.get('execution_user') != control.ssh_user):
            continue
        try:
            runtime = _capability(result.get('functional_runtime'))
        except (ValueError, TypeError):
            continue
        return {'job_id': job.id, 'machine_id': control.id, 'execution_user': control.ssh_user,
                'immutable_path': path, 'functional_runtime': runtime}
    raise Problem(422, 'runtime_install_required', '需要显式安装支持引导功能测试的固定版本工具包')


def _evaluate(db, actor, request, pinned=None, owner=None):
    settings = _settings(db)
    if not settings.functional_guided_enabled:
        raise Problem(503, 'guided_runs_disabled', '引导功能测试尚未启用')
    # Inventory/permission mutations use this same lock. Keep it before fresh
    # authorization and before sorted lease locks, including direct worker calls.
    lock_accounts(db)
    fresh_actor = db.get(User, actor.id, populate_existing=True)
    cluster = db.get(Cluster, request.cluster_id, populate_existing=True)
    if not fresh_actor or fresh_actor.disabled or not cluster or cluster.archived:
        raise Problem(403, 'forbidden', '账号或集群不可用')
    require_manage(fresh_actor, cluster)
    control = db.get(Machine, cluster.management_machine_id, populate_existing=True)
    if not control or control.archived or control.maintenance:
        raise Problem(422, 'machine_unavailable', '管理机器不可用')
    require_manage(fresh_actor, control)
    fresh = resolve_submission(db, fresh_actor, RunSpec(**request.model_dump(include=set(RunSpec.model_fields))))
    if fresh.request_digest != request.request_digest:
        raise Problem(409, 'preflight_changed', '请求或环境源已改变，请重新预检')
    checks, impacts = [], []
    def check(code, ok, **metadata):
        checks.append({'code': code, 'ok': bool(ok), **metadata})
    # Authorize the full union, including read/status and declared SSH identities,
    # before making any connection, and preserve the actual execution username.
    targets = {}
    for snapshot in request.environment_snapshots.values():
        descriptor = EnvironmentDescriptor.model_validate(snapshot)
        check('source_compatible', not descriptor.issues and all(c.available for c in descriptor.modules.values()))
        check('cluster_identity', bool(descriptor.mds_addresses) and
              set(descriptor.mds_addresses) == set((cluster.status_snapshot or {}).get('mds_addresses') or []))
        for target in descriptor.targets:
            targets[(target.host, target.user)] = _target(db, fresh_actor, target.host)
        for module, capability in descriptor.modules.items():
            for impact in capability.impacts:
                impacts.append({'module': module, 'description': impact})
    requests = functional_requests(db, cluster.id, control.id, request.environment_snapshots.values(), actor=fresh_actor)
    conflicts = check_conflicts(db, requests, owner)
    check('resource_available', not conflicts, conflicts=[{'key': c.key, 'owner': c.owner, 'reason': c.reason} for c in conflicts])
    for (host, user), machine in targets.items():
        check('authentication_supported', bool(user) and user == machine.ssh_user and bool(machine.ssh_password_ciphertext),
              host=host, user=user)
    binding = _binding(db, control, pinned)
    binding['resolved_targets'] = sorted([
        {'source_host': host, 'machine_id': machine.id, 'machine_name': machine.name, 'address': machine.address,
         'port': machine.ssh_port, 'user': user}
        for (host, user), machine in targets.items()], key=lambda item: (item['source_host'], item['user']))
    approved = set()
    for snapshot in request.environment_snapshots.values():
        for target in snapshot['targets']:
            machine = targets[(target['host'], target['user'])]
            for host in (target['host'], machine.address):
                approved.add((host, target['user'], target['role'], target['mutates']))
    binding['approved_targets'] = [{'host': host, 'user': user, 'role': role, 'mutates': mutates}
                                   for host, user, role, mutates in sorted(approved)]
    binding['control_connection'] = [control.address, control.ssh_port, control.ssh_user]
    if pinned and binding != {k: v for k, v in pinned.items() if k != 'observations'}:
        raise Problem(409, 'preflight_changed', '固定运行时安装记录已改变')
    runtime = binding['functional_runtime']
    root = Path(settings.functional_source_root).parent.resolve()
    for snapshot in request.environment_snapshots.values():
        check('runtime_source_bound', all(runtime['source_manifest'].get(p) == h for p,h in snapshot['source_manifest'].items()))
    # The complete package framework manifest (including Python code) is checked,
    # not merely the selected environment YAML/case subset.
    try:
        required_sources = {p.relative_to(root).as_posix() for subdir, pattern in (
            ('src', '*.py'), ('conf', '*.yaml'), ('testcases', '*.yaml'), ('template', '*.py'))
            for p in (root / subdir).rglob(pattern) if p.is_file()}
        source_ok = bool(required_sources) and required_sources <= runtime['source_manifest'].keys() and all((root / p).resolve().is_relative_to(root) and
                        hashlib.sha256((root / p).read_bytes()).hexdigest() == h
                        for p,h in runtime['source_manifest'].items())
    except (OSError, RuntimeError):
        source_ok = False
    check('runtime_source_version', source_ok)
    if not all(c['ok'] for c in checks):
        return checks, impacts, binding
    response = _transport(db, control, control.ssh_user,
                          [binding['immutable_path'], '--functional-capabilities', '--format', 'json'])
    try:
        observed = _capability(response)
    except (TypeError, ValueError):
        check('runtime_version', False)
        return checks, impacts, binding
    check('runtime_version', observed == runtime)
    if observed != runtime:
        return checks, impacts, binding
    binding['observations'] = []
    for snapshot in request.environment_snapshots.values():
        snapshot_targets = {(t['host'], t['user']): targets[(t['host'], t['user'])] for t in snapshot['targets']}
        authentication = [{'user': user, 'value': decrypt_password(machine.ssh_password_ciphertext,
                           settings.credential_encryption_key)} for (host, user), machine in snapshot_targets.items()]
        projection = project_source(root, snapshot['env_name'], authentication=authentication)
        del authentication
        execution = projection['execution']
        check('storage_configuration', execution['storage_ready'])
        check('authentication_mode_supported', execution['authentication_mode'] == 'password')
        check('source_authentication', execution['authentication_matches'])
        if not execution['authentication_matches'] or not execution['storage_ready']:
            continue
        for (host, user), machine in snapshot_targets.items():
            clients = [c for c in execution['clients'] if c['host'] == host]
            caches = [c for c in execution['caches'] if c['host'] == host]
            tools = {'python3'}
            if clients: tools |= {'findmnt', 'numactl'}
            binaries = [c['binary'] for c in clients + caches if c['binary']]
            requirements = {tool for capability in snapshot['modules'].values() for tool in capability['required_tools']}
            if 'dingo' in requirements:
                binaries.append(execution['dingo'])
            if 'mds-client' in requirements:
                path = snapshot['programs'].get('mds_client')
                check('mds_client_configuration', bool(path), host=host, user=user)
                if path: binaries.append(path)
            if 'fault-recovery' in requirements:
                check('fault_recovery_configuration', not snapshot['programs'].get('chaos_tool'))
            tools.update(requirements - {'dingo', 'mds-client', 'client-binary', 'cache-binary', 'fault-recovery'})
            if clients and any(not c['binary'] for c in clients): tools.add('dingo-client')
            if caches and any(not c['binary'] for c in caches): tools.add('dingo-cache')
            fs_query = []
            if host == execution['command_host']:
                binaries.append(execution['dingo'])
                fs_query = [execution['dingo'], 'fs', 'list', '--mdsaddr', ','.join(snapshot['mds_addresses']), '--format', 'json']
            spec = {'user': user, 'tools': sorted(tools), 'binaries': sorted(set(binaries)),
                    'paths': sorted({p for c in clients + caches for p in c['paths']} | {c['mount_path'] for c in clients}),
                    'ports': sorted({c['port'] for c in clients + caches}), 'cache': bool(caches), 'client': bool(clients),
                    'fs_query': fs_query, 'mount_roots': [c['mount_path'] for c in clients], 'mds': ','.join(snapshot['mds_addresses']),
                    'fixed_names': sorted({name for c in snapshot['modules'].values() for name in c['fixed_resources']})}
            result = _transport(db, machine, user, ['python3', '-I', '-B', '-c', READ_ONLY_PROBE, json.dumps(spec)])
            if (not isinstance(result, dict) or result.get('user') != user or not isinstance(result.get('checks'), dict)
                    or set(result['checks']) != set(PROBE_CHECKS) or any(type(v) is not bool for v in result['checks'].values())
                    or not isinstance(result.get('fingerprint'), str) or not re.fullmatch(r'[0-9a-f]{64}', result['fingerprint'])):
                raise Problem(422, 'remote_probe_failed', '只读检查结果无效')
            binding['observations'].append({'env_name': snapshot['env_name'], 'host': host, 'user': user,
                                            'fingerprint': result['fingerprint']})
            for code, ok in result['checks'].items():
                check(code, ok, host=host, user=user)
    impacts.append({'description': '平台资源占用不覆盖外部 Jenkins 或人工操作；执行及清理期间禁止共同使用测试资源。'})
    return checks, impacts, binding


def preflight(db, actor, request: NormalizedSubmission) -> PreflightResult:
    try:
        checks, impacts, binding = _evaluate(db, actor, request)
    except Problem as exc:
        if exc.status in (403, 404, 409):
            raise
        return PreflightResult(can_start=False, checks=[{'code': exc.code, 'ok': False}])
    except (ValueError, TypeError, KeyError):
        return PreflightResult(can_start=False, checks=[{'code': 'preflight_invalid', 'ok': False}])
    confirmations = sorted({_digest(impact) for impact in impacts})
    if not all(c['ok'] for c in checks):
        return PreflightResult(can_start=False, checks=checks, impacts=impacts, required_confirmations=confirmations)
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(seconds=600)
    db.add(FunctionalPreflight(creator_id=actor.id, token_hash=hashlib.sha256(token.encode()).hexdigest(),
        request_digest=request.request_digest, source_digest=_digest(binding), expires_at=expires,
        checks=[*checks, {'code': 'runtime_binding', 'ok': True, 'binding': binding}],
        required_confirmations=confirmations, can_start=True))
    db.flush()
    return PreflightResult(can_start=True, token=token, expires_at=expires, checks=checks,
                           required_confirmations=confirmations, impacts=impacts)


def validate_preflight(db, actor, request: NormalizedSubmission, token: str, confirmed_impacts: list[str]):
    """Submit gate: owner/input/TTL/confirmation checks plus fresh remote validation.

    Caller binds consumed_by to the created parent in the same transaction.
    Queue launch uses revalidate_binding, which does not extend token validity.
    """
    query = select(FunctionalPreflight).where(FunctionalPreflight.token_hash == hashlib.sha256(token.encode()).hexdigest())
    row = db.scalar(query)
    if (not row or row.creator_id != actor.id or not row.can_start or row.consumed_by
            or row.expires_at <= datetime.now(timezone.utc) or row.request_digest != request.request_digest
            or not set(row.required_confirmations) <= set(confirmed_impacts)):
        raise Problem(409, 'preflight_changed', '预检已失效或影响尚未确认，请重新预检')
    binding = next((c['binding'] for c in row.checks if c['code'] == 'runtime_binding'), None)
    revalidate_binding(db, actor, request, binding)
    # Respect Task8 ordering: account/lease locks before the business token row.
    row = db.scalar(query.with_for_update().execution_options(populate_existing=True))
    if not row or row.consumed_by or row.expires_at <= datetime.now(timezone.utc) or row.source_digest != _digest(binding):
        raise Problem(409, 'preflight_changed', '预检已失效，请重新预检')
    return {'preflight_id': row.id, 'runtime_binding': binding}


def revalidate_binding(db, actor, request, binding, *, owner=None):
    """Task10 queue-start gate. Rechecks frozen path, permissions and sources."""
    if not binding:
        raise Problem(409, 'preflight_changed', '固定运行时绑定缺失')
    try:
        checks, _, actual = _evaluate(db, actor, request, pinned=binding, owner=owner)
    except Problem:
        raise
    except Exception:
        raise Problem(409, 'preflight_changed', '只读复检失败') from None
    if actual != binding or not all(c['ok'] for c in checks):
        raise Problem(409, 'preflight_changed', '权限、工具或源版本已改变，请重新预检')
    return binding
