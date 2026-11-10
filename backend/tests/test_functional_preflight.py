"""Real source/database preflight with fake, strictly read-only remote I/O."""
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import pytest
from sqlalchemy import select
from conftest import linked, machine
from functional_source_fixture import copy_trusted_protocol
from dingofs_platform.auth.models import User
from dingofs_platform.functional.models import FunctionalPreflight
from dingofs_platform.functional.schemas import RunSpec
from dingofs_platform.inventory.models import Cluster, Machine
from dingofs_platform.tool_packages.models import ToolJob


def api():
    assert importlib.util.find_spec('dingofs_platform.functional.preflight'), 'guided preflight is missing'
    from dingofs_platform.functional import preflight
    return preflight


@pytest.fixture(autouse=True)
def deny_real_ssh(monkeypatch):
    import paramiko
    def deny(*args, **kwargs):
        raise AssertionError('real SSH is forbidden')
    monkeypatch.setattr(paramiko.SSHClient, 'connect', deny)
    # Production SSH uses multiprocessing spawn, so a Paramiko-only patch in
    # this process would not guard its child. Deny the spawning boundary too.
    if importlib.util.find_spec('dingofs_platform.functional.preflight'):
        from dingofs_platform.functional import preflight as module
        monkeypatch.setattr(module, 'execute', deny)


class ReadOnlyRemote:
    def __init__(self, runtime):
        self.runtime, self.calls, self.failed_check = runtime, [], None
        self.fingerprint = 'c' * 64

    def __call__(self, machine, user, argv):
        self.calls.append((machine.id, user, argv))
        if argv == ['/opt/dtt/immutable-123/dtt', '--functional-capabilities', '--format', 'json']:
            return copy.deepcopy(self.runtime)
        assert argv[:4] == ['python3', '-I', '-B', '-c'], 'only isolated non-bytecode-writing Python probes allowed'
        request = json.loads(argv[5])
        assert request['user'] == user
        assert not {'mds-client', 'client-binary', 'cache-binary', 'fault-recovery'} & set(request['tools'])
        checks = {name: True for name in ('identity', 'tools', 'binaries', 'directories', 'ports',
                  'proc', 'pidfd', 'fuse_cleanup', 'filesystem_schema', 'mount_identity')}
        if self.failed_check:
            checks[self.failed_check] = False
        return {'user': user, 'checks': checks, 'fingerprint': self.fingerprint}


@pytest.fixture
def ready(admin, app, tmp_path):
    control, cluster, _ = linked(admin)
    root = tmp_path / 'source'
    copy_trusted_protocol(root)
    (root / 'conf/env').mkdir(parents=True)
    (root / 'conf/env/base.yaml').write_text('''template:
  run_as_user: test/test-secret
  mds_addr: node1.test:6900
  dingo_tool_path: /opt/dingo
  mds_client_path: /opt/dingo-mds-client
  storage: {storage_type: s3, storage_env: store}
  clients:
    - host: node1.test
      fs_name: sample
      mount_path: /mnt/functional
      client_bin_path: /opt/dingo-client
''')
    (root / 'conf/env/child.yaml').write_text('env_ready:\n  base: template\n')
    (root / 'conf/storage.yaml').write_text('store:\n  s3: {s3_ak: private-ak, s3_sk: private-sk, s3_endpoint: http://store, s3_bucketname: bucket}\n')
    (root / 'testcases/quota_test_cases').mkdir(parents=True)
    (root / 'testcases/quota_test_cases/case.yaml').write_text('case_name: fixture\nsteps: []\n')
    app.state.settings.functional_source_root = root / 'testcases'
    app.state.settings.functional_guided_enabled = True
    with app.state.session_factory.begin() as db:
        db.get(Cluster, cluster['id']).status_snapshot = {'mds_addresses': ['node1.test:6900']}
    assert admin.post('/api/v1/functional/environments/sync-predefined').status_code == 200
    profiles = admin.get('/api/v1/functional/environments').json()
    profile = next(p for p in profiles if p['source_key'] == 'env_ready')
    from dingofs_platform.functional.catalog import catalogue
    catalog = catalogue(root / 'testcases')
    spec = RunSpec(name='safe', cluster_id=cluster['id'], catalog_digest=catalog['digest'],
        module_plans=[{'module': 'quota', 'environment_profile_id': profile['id'],
                       'environment_profile_revision': profile['revision'], 'cases': ['case.yaml']}])
    manifest = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob('*') if p.is_file()}
    runtime = {'version': 2, 'features': ['exact_case_plan_v1', 'runtime_context_v1', 'owned_cleanup_v1',
        'lifecycle_events_v2', 'cancel_boundary_v1', 'inspection_v1'],
        'image_id': 'sha256:' + 'a' * 64, 'files': {'dtt': 'b' * 64}, 'source_manifest': manifest}
    with app.state.session_factory.begin() as db:
        actor = db.scalar(select(User).where(User.username == 'admin'))
        db.add(ToolJob(machine_id=control['id'], creator_id=actor.id, action='install', state='success',
            deadline=datetime.now(timezone.utc), result={'immutable_path': '/opt/dtt/immutable-123/dtt',
            'execution_user': 'test', 'functional_runtime': copy.deepcopy(runtime)}))
    remote = ReadOnlyRemote(runtime)
    app.state.functional_preflight_transport = remote
    return spec, root, remote, control, profile


def invoke(app, ready, *, token=None, confirmations=()):
    module = api()
    with app.state.session_factory.begin() as db:
        db.info['functional_settings'] = app.state.settings
        db.info['functional_preflight_transport'] = app.state.functional_preflight_transport
        actor = db.scalar(select(User).where(User.username == 'admin'))
        normalized = module.resolve_submission(db, actor, ready[0])
        if token:
            return module.validate_preflight(db, actor, normalized, token, list(confirmations))
        return module.preflight(db, actor, normalized)


def test_preflight_has_zero_remote_mutations(app, ready):
    result = invoke(app, ready)
    assert result.can_start and result.token
    assert 598 <= (result.expires_at - datetime.now(timezone.utc)).total_seconds() <= 600
    assert result.required_confirmations
    with app.state.session_factory() as db:
        row = db.scalar(select(FunctionalPreflight))
        assert row.token_hash != result.token and row.token_hash == hashlib.sha256(result.token.encode()).hexdigest()
        assert 'private-' not in json.dumps(row.checks)
    assert {user for _, user, _ in ready[2].calls} == {'test'}


def test_changed_input_cannot_reuse_token(app, ready):
    result = invoke(app, ready)
    ready = (ready[0].model_copy(update={'retries': 1}), *ready[1:])
    from dingofs_platform.errors import Problem
    with pytest.raises(Problem) as error:
        invoke(app, ready, token=result.token, confirmations=result.required_confirmations)
    assert error.value.code == 'preflight_changed'


@pytest.mark.parametrize('relative', ['conf/env/base.yaml', 'conf/storage.yaml'])
def test_base_drift_invalidates_token(app, ready, relative):
    result = invoke(app, ready)
    path = ready[1] / relative
    path.write_text(path.read_text() + '\n# changed\n')
    from dingofs_platform.errors import Problem
    with pytest.raises(Problem):
        invoke(app, ready, token=result.token, confirmations=result.required_confirmations)


def test_runtime_drift_and_permissions_rechecked_with_live_token(app, ready):
    result = invoke(app, ready)
    ready[2].runtime['image_id'] = 'sha256:' + 'f' * 64
    from dingofs_platform.errors import Problem
    with pytest.raises(Problem) as error:
        invoke(app, ready, token=result.token, confirmations=result.required_confirmations)
    assert error.value.code == 'preflight_changed'
    with app.state.session_factory.begin() as db:
        db.get(Machine, ready[3]['id']).maintenance = True
    with pytest.raises(Problem):
        invoke(app, ready, token=result.token, confirmations=result.required_confirmations)


def test_old_remote_capabilities_have_an_explicit_version_reason(app, ready):
    ready[2].runtime['version'] = 1
    result = invoke(app, ready)
    assert not result.can_start
    assert any(c['code'] == 'runtime_version' and not c['ok'] for c in result.checks)


@pytest.mark.parametrize('check', ['identity', 'tools', 'binaries', 'directories', 'ports', 'proc', 'pidfd',
                                  'fuse_cleanup', 'filesystem_schema', 'mount_identity'])
def test_missing_remote_prerequisite_refuses_without_token(app, ready, check):
    ready[2].failed_check = check
    result = invoke(app, ready)
    assert not result.can_start and result.token is None
    assert any(check in item['code'] for item in result.checks if not item['ok'])


def test_preflight_api_is_gated_and_does_not_launch(admin, app, ready):
    result = admin.post('/api/v1/functional/preflight', json=ready[0].model_dump())
    assert result.status_code == 200, result.text
    assert result.json()['can_start']
    app.state.settings.functional_guided_enabled = False
    assert admin.post('/api/v1/functional/preflight', json=ready[0].model_dump()).status_code == 503


def test_registration_address_change_invalidates_frozen_target(app, ready):
    result = invoke(app, ready)
    with app.state.session_factory.begin() as db:
        row = db.get(Machine, ready[3]['id'])
        row.aliases = [row.address]
        row.address = 'different.test'
    from dingofs_platform.errors import Problem
    with pytest.raises(Problem) as error:
        invoke(app, ready, token=result.token, confirmations=result.required_confirmations)
    assert error.value.code == 'preflight_changed'


def test_expiry_and_confirmation_required_and_queue_rechecks(app, ready):
    result = invoke(app, ready)
    from dingofs_platform.errors import Problem
    with pytest.raises(Problem):
        invoke(app, ready, token=result.token)
    binding = invoke(app, ready, token=result.token, confirmations=result.required_confirmations)
    assert binding['runtime_binding']['approved_targets'] == [
        {'host': 'node1.test', 'user': 'test', 'role': 'client', 'mutates': True},
        {'host': 'node1.test', 'user': 'test', 'role': 'mds', 'mutates': True}]
    with app.state.session_factory.begin() as db:
        row = db.scalar(select(FunctionalPreflight))
        row.expires_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(Problem):
        invoke(app, ready, token=result.token, confirmations=result.required_confirmations)


def test_source_manifest_cannot_omit_framework_code(app, ready):
    ready[2].runtime['source_manifest'].pop('src/test_runner/functional_contracts.py')
    with app.state.session_factory.begin() as db:
        job = db.scalar(select(ToolJob).where(ToolJob.action == 'install'))
        job.result = {**job.result, 'functional_runtime': copy.deepcopy(ready[2].runtime)}
    result = invoke(app, ready)
    assert not result.can_start


@pytest.mark.parametrize('role', ['cache', 'case', 'mds'])
def test_cache_fault_and_mds_hosts_require_permission(admin, app, ready, monkeypatch, role):
    other = machine(admin, 'other')
    from dingofs_platform.functional import preflight as module
    real = module.inspect_source
    def source(*args, **kwargs):
        descriptor = real(*args, **kwargs)
        from dingofs_platform.functional.contracts import Target
        if args[2]:
            return descriptor.model_copy(update={'targets': [*descriptor.targets,
                Target(role=role, host='other.test', user='test', mutates=role != 'mds')]})
        return descriptor
    monkeypatch.setattr(module, 'inspect_source', source)
    with app.state.session_factory.begin() as db:
        actor = db.scalar(select(User).where(User.username == 'admin'))
        member = db.scalar(select(User).where(User.username == 'member'))
        actor.role = 'member'
        db.get(Machine, other['id']).creator_id = member.id
    from dingofs_platform.errors import Problem
    with pytest.raises(Problem) as error:
        invoke(app, ready)
    assert error.value.code == 'forbidden'
    assert ready[2].calls == []


def test_execution_account_not_confused_with_login_user(app, ready):
    with app.state.session_factory.begin() as db:
        db.get(Machine, ready[3]['id']).ssh_user = 'login-only'
    result = invoke(app, ready)
    assert not result.can_start
    assert ready[2].calls == []


def test_unconfirmed_install_and_remote_exception_are_safe(app, ready):
    with app.state.session_factory.begin() as db:
        job = db.scalar(select(ToolJob).where(ToolJob.action == 'install'))
        job.state = 'running'
    result = invoke(app, ready)
    assert not result.can_start and result.checks[0]['code'] == 'runtime_install_required'
    assert ready[2].calls == []


def test_read_only_probe_checks_real_parent_identity_and_missing_tools(tmp_path, monkeypatch, capsys):
    module = api()
    import os, pwd, sys
    folder = tmp_path / 'real'
    folder.mkdir()
    link = tmp_path / 'link'
    link.symlink_to(folder)
    request = {'user': pwd.getpwuid(os.geteuid()).pw_name, 'tools': ['no-such-preflight-tool'],
               'binaries': [], 'paths': [str(link / 'child')], 'ports': [], 'cache': False,
               'client': False, 'fs_query': [], 'mount_roots': [], 'mds': ''}
    monkeypatch.setattr(sys, 'argv', ['probe', json.dumps(request)])
    exec(compile(module.READ_ONLY_PROBE, '<read-only probe>', 'exec'), {})
    answer = json.loads(capsys.readouterr().out)
    assert answer['checks']['identity']
    assert not answer['checks']['tools'] and not answer['checks']['directories']


def test_source_password_must_match_the_authentication_actually_probed(app, ready):
    from dingofs_platform.inventory.credentials import encrypt_password
    with app.state.session_factory.begin() as db:
        db.get(Machine, ready[3]['id']).ssh_password_ciphertext = encrypt_password(
            'different-credential', app.state.settings.credential_encryption_key)
    result = invoke(app, ready)
    assert not result.can_start
    assert any(item['code'] == 'source_authentication' and not item['ok'] for item in result.checks)


def test_unreadable_credentials_have_a_safe_reason(app, ready):
    with app.state.session_factory.begin() as db:
        db.get(Machine, ready[3]['id']).ssh_password_ciphertext = 'unreadable-ciphertext'
    result = invoke(app, ready)
    assert not result.can_start and not result.token
    assert result.checks[0]['code'] == 'credential_decryption_failed'
    assert 'unreadable-ciphertext' not in result.model_dump_json()


def test_disabled_feature_blocks_queued_revalidation(app, ready):
    result = invoke(app, ready)
    bound = invoke(app, ready, token=result.token, confirmations=result.required_confirmations)
    app.state.settings.functional_guided_enabled = False
    from dingofs_platform.errors import Problem
    with app.state.session_factory.begin() as db:
        db.info['functional_settings'] = app.state.settings
        db.info['functional_preflight_transport'] = ready[2]
        actor = db.scalar(select(User).where(User.username == 'admin'))
        module = api()
        request = module.resolve_submission(db, actor, ready[0])
        with pytest.raises(Problem) as error:
            module.revalidate_binding(db, actor, request, bound['runtime_binding'])
        assert error.value.code == 'guided_runs_disabled'


def test_transport_error_is_redacted_without_a_token(app, ready):
    def fail(*args):
        raise RuntimeError('SECRET remote exception with source passwords')
    app.state.functional_preflight_transport = fail
    result = invoke(app, ready)
    assert not result.can_start and not result.token
    assert 'SECRET' not in result.model_dump_json()


def test_binary_or_parent_identity_change_invalidates_token(app, ready):
    result = invoke(app, ready)
    ready[2].fingerprint = 'd' * 64
    from dingofs_platform.errors import Problem
    with pytest.raises(Problem):
        invoke(app, ready, token=result.token, confirmations=result.required_confirmations)


def test_legacy_descriptor_needs_remote_binding_even_with_complete_local_source(app, ready):
    from dingofs_platform.operations.leases import legacy_functional_requests
    from dingofs_platform.errors import Problem
    snapshot = {'env_name': 'env_ready', 'selected': {'quota': ['case.yaml']},
        'environment_profile_snapshot': {'kind': 'predefined', 'source_file': 'child.yaml',
            'source_file_sha': ready[4]['display']['source_file_sha'],
            'storage_file_sha': ready[4]['display']['storage_file_sha']}}
    with app.state.session_factory.begin() as db:
        actor = db.scalar(select(User).where(User.username == 'admin'))
        with pytest.raises(Problem) as error:
            legacy_functional_requests(db, ready[0].cluster_id, ready[3]['id'], snapshot,
                ready[1] / 'testcases', actor=actor, strict=True)
        assert error.value.code == 'target_unresolved'
        # Only a trusted server caller that actually verified the remote source
        # may supply this evidence; it is never accepted from an HTTP payload.
        requests = legacy_functional_requests(db, ready[0].cluster_id, ready[3]['id'], snapshot,
            ready[1] / 'testcases', actor=actor, strict=True, source_bound=True)
        assert 'machine:' + ready[3]['id'] in {r.key for r in requests}


@pytest.mark.parametrize('fs_id,source,option,valid', [
    (12, 'DingoFS:sample', '--mdsaddr=node1.test:6900', True),
    (12, 'mds://node1.test:6900/sample', '--mdsaddr=node1.test:6900', True),
    ('unknown', 'DingoFS:sample', '--mdsaddr=node1.test:6900', False),
    (12, 'DingoFS:other', '--mdsaddr=node1.test:6900', False),
    (12, 'DingoFS:sample', '--mdsaddr=elsewhere:6900', False),
])
def test_real_read_only_probe_exact_fs_mount_and_process(tmp_path, monkeypatch, capsys, fs_id, source, option, valid):
    module = api()
    import os, pwd, sys, subprocess
    from pathlib import Path
    from types import SimpleNamespace
    folder = tmp_path / 'mount'
    folder.mkdir()
    process = tmp_path / '123'
    process.mkdir()
    (process / 'comm').write_text('dingo-client\n')
    (process / 'stat').write_text('123 (dingo-client) ' + ' '.join(['S'] + ['0'] * 18 + ['123']))
    (process / 'cmdline').write_bytes(('dingo-client\0--fsname=sample\0' + option + '\0--mountpoint=' + str(folder) + '\0').encode())
    (process / 'exe').symlink_to('/usr/bin/dingo-client')
    original = Path.iterdir
    monkeypatch.setattr(Path, 'iterdir', lambda p: iter([process]) if str(p) == '/proc' else original(p))
    def query(argv, **kwargs):
        if argv == ['/opt/dingo', 'fs', 'list', '--mdsaddr', 'node1.test:6900', '--format', 'json']:
            data = [{'fs_name': 'sample', 'fs_id': fs_id}]
        elif argv == ['findmnt', '--json', '--output', 'ID,TARGET,SOURCE,FSTYPE']:
            data = {'filesystems': [{'id': 42, 'target': str(folder), 'source': source, 'fstype': 'fuse.dingofs'}]}
        else:
            raise AssertionError('mutating or unapproved subprocess command')
        return SimpleNamespace(returncode=0, stdout=json.dumps(data), stderr='')
    monkeypatch.setattr(subprocess, 'run', query)
    request = {'user': pwd.getpwuid(os.geteuid()).pw_name, 'tools': [], 'binaries': [],
        'paths': [str(folder)], 'ports': [], 'cache': False, 'client': False,
        'fs_query': ['/opt/dingo', 'fs', 'list', '--mdsaddr', 'node1.test:6900', '--format', 'json'],
        'mount_roots': [str(folder)], 'mds': 'node1.test:6900'}
    monkeypatch.setattr(sys, 'argv', ['probe', json.dumps(request)])
    exec(compile(module.READ_ONLY_PROBE, '<read-only probe>', 'exec'), {})
    checks = json.loads(capsys.readouterr().out)['checks']
    assert (checks['filesystem_schema'] and checks['mount_identity']) is valid


@pytest.mark.parametrize('payload,fixed_names,valid', [
    ([], [], True),
    ({'result': {'fs_infos': []}}, [], True),
    ({'result': {'fs_infos': []}}, ['shared-fixed'], True),
    ({'result': {'fs_infos': [{'fs_name': 'other', 'fs_id': 12}]}}, ['shared-fixed'], True),
    ({'result': {'fs_infos': [{'fs_name': 'shared-fixed', 'fs_id': 12}]}}, ['shared-fixed'], True),
    ({'result': {'fs_infos': [{'fs_name': 'shared-fixed', 'fs_id': 'unknown'}]}}, ['shared-fixed'], False),
    ({'result': {'fs_infos': [{'fs_name': 'shared-fixed', 'fs_id': 12}] * 2}}, ['shared-fixed'], False),
    ({'result': {'fs_infos': [{}]}}, [], False),
    ({'result': {'unexpected': []}}, [], False),
    ({'result': {'fs_infos': {}}}, [], False),
    ({}, [], False),
])
def test_filesystem_schema_allows_create_or_borrow_without_renaming(monkeypatch, capsys, payload, fixed_names, valid):
    import os, pwd, sys, subprocess
    from types import SimpleNamespace
    command = ['/opt/dingo', 'fs', 'list', '--mdsaddr', 'node1.test:6900', '--format', 'json']
    def query(argv, **kwargs):
        assert argv == command, 'only the read-only filesystem query is allowed'
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr='')
    monkeypatch.setattr(subprocess, 'run', query)
    request = {'user': pwd.getpwuid(os.geteuid()).pw_name, 'tools': [], 'binaries': [],
        'paths': [], 'ports': [], 'cache': False, 'client': False, 'fs_query': command,
        'mount_roots': [], 'mds': 'node1.test:6900', 'fixed_names': fixed_names}
    monkeypatch.setattr(sys, 'argv', ['probe', json.dumps(request)])
    exec(compile(api().READ_ONLY_PROBE, '<read-only probe>', 'exec'), {})
    assert json.loads(capsys.readouterr().out)['checks']['filesystem_schema'] is valid


@pytest.mark.parametrize('relative', ['conf/env/base.yaml', 'src/config/env_parser.py', 'testcases/quota_test_cases/case.yaml'])
def test_source_change_during_capability_reply_stops_before_prerequisite_probe(app, ready, relative):
    original = ready[2]
    def mutate(machine, user, argv):
        answer = original(machine, user, argv)
        if '--functional-capabilities' in argv:
            path = ready[1] / relative
            path.write_text(path.read_text().replace('/mnt/functional', '/mnt/changed') + '\n# source changed during capability reply\n')
        return answer
    app.state.functional_preflight_transport = mutate
    result = invoke(app, ready)
    assert not result.can_start and result.token is None
    assert any(c['code'] == 'projection_source_bound' and not c['ok'] for c in result.checks)
    assert len(original.calls) == 1
    with app.state.session_factory() as db:
        assert db.scalar(select(FunctionalPreflight)) is None


@pytest.mark.parametrize('module_name,client_binary,with_cache,node_count', [
    ('quota', '/opt/dingo-client', False, 0), ('client', '/opt/dingo-client', False, 0),
    ('client', '', False, 0), ('quota', '/opt/dingo-client', True, 0), ('cache_node', '', True, 0),
    ('mds_manage', '/unused/dingo-client', True, 0), ('hot_upgrade', '/unused/dingo-client', False, 0),
    ('hot_upgrade', '/unused/dingo-client', True, 2)])
def test_partitioned_tool_inventory_matches_actual_command_and_mount_hosts(admin, app, ready, module_name, client_binary, with_cache, node_count):
    from dingofs_platform.inventory.credentials import encrypt_password
    from dingofs_platform.functional.catalog import MODULE_DIRS, catalogue
    other = machine(admin, 'other')
    with app.state.session_factory.begin() as db:
        db.get(Machine, other['id']).ssh_password_ciphertext = encrypt_password(
            'test-secret', app.state.settings.credential_encryption_key)
    path = ready[1] / 'conf/env/base.yaml'
    content = path.read_text().replace('host: node1.test', 'host: other.test')
    content = content.replace('client_bin_path: /opt/dingo-client',
        'dingo_tool_path: /client/dingo\n      client_bin_path: ' + json.dumps(client_binary))
    content += f'  mds_node_count: {node_count}\n'
    if module_name == 'hot_upgrade':
        content += '  smooth_upgrade_target_client_binary: /upgrade/dingo-client\n'
    if with_cache:
        content += '''  remote_caches:
    - host: other.test
      dingo_tool_path: /cache/dingo
      cache_bin_path: /unused/dingo-cache
      remote_cache_conf: {--group_name: task-cache}
'''
    path.write_text(content)
    if module_name != 'quota':
        folder = ready[1] / 'testcases' / MODULE_DIRS[module_name]
        folder.mkdir()
        (folder / 'case.yaml').write_text('case_name: fixture\nsteps: []\n')
    assert admin.post('/api/v1/functional/environments/sync-predefined').status_code == 200
    profile = next(p for p in admin.get('/api/v1/functional/environments').json() if p['source_key'] == 'env_ready')
    spec = ready[0].model_copy(update={'catalog_digest': catalogue(ready[1] / 'testcases')['digest'],
        'module_plans': [ready[0].module_plans[0].model_copy(update={'module': module_name,
            'environment_profile_revision': profile['revision']})]})
    ready[2].runtime['source_manifest'] = {p.relative_to(ready[1]).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in ready[1].rglob('*') if p.is_file()}
    with app.state.session_factory.begin() as db:
        job = db.scalar(select(ToolJob).where(ToolJob.action == 'install'))
        job.result = {**job.result, 'functional_runtime': copy.deepcopy(ready[2].runtime)}
    def partitioned(machine, user, argv):
        answer = ready[2](machine, user, argv)
        if '--functional-capabilities' in argv:
            return answer
        probe = json.loads(argv[5])
        command_bins = {'/opt/dingo'} if module_name == 'hot_upgrade' and not node_count else {'/opt/dingo', '/opt/dingo-mds-client'}
        available = command_bins if machine.id == ready[3]['id'] else (
            set() if module_name == 'mds_manage' else
            {'/upgrade/dingo-client', '/client/dingo', '/cache/dingo'} if module_name == 'hot_upgrade' else
            {'/cache/dingo'} if module_name == 'cache_node' else
            {'/opt/dingo-client'} if module_name == 'client' and client_binary else {'/client/dingo', '/cache/dingo'})
        answer['checks']['binaries'] = set(probe['binaries']) <= available
        answer['checks']['tools'] = set(probe['tools']) <= (
            {'python3'} if machine.id == ready[3]['id'] else {'python3', 'findmnt', 'numactl'})
        return answer
    app.state.functional_preflight_transport = partitioned
    result = invoke(app, (spec, *ready[1:]))
    assert result.can_start, result.model_dump()
    probes = {mid: json.loads(argv[5]) for mid, _, argv in ready[2].calls if argv[0] == 'python3'}
    expected = [] if module_name in {'cache_node', 'mds_manage'} else [client_binary] if module_name == 'client' and client_binary else ['/client/dingo']
    if with_cache and module_name != 'mds_manage': expected.append('/cache/dingo')
    if module_name == 'hot_upgrade': expected.append('/upgrade/dingo-client')
    assert probes[other['id']]['binaries'] == sorted(expected)
    assert probes[ready[3]['id']]['fs_query'] and not probes[other['id']]['fs_query']
    if module_name == 'mds_manage':
        assert not probes[other['id']]['paths'] and not probes[other['id']]['ports']
        assert not probes[other['id']]['client'] and not probes[other['id']]['cache']
    # Readiness must also fail if an executable actually used on this host is
    # missing. Moving every tool to the command host must not pass this test.
    def missing_used_executable(machine, user, argv):
        answer = partitioned(machine, user, argv)
        missing_host = other['id'] if expected else ready[3]['id']
        missing_bins = set(expected) if expected else {'/opt/dingo'}
        if machine.id == missing_host and argv[0] == 'python3':
            answer['checks']['binaries'] = not set(json.loads(argv[5])['binaries']) & missing_bins
        return answer
    app.state.functional_preflight_transport = missing_used_executable
    assert not invoke(app, (spec, *ready[1:])).can_start
