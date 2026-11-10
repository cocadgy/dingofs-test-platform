"""Exercise the real pure framework protocol in a temporary trusted checkout."""
import hashlib
import json
import pytest
from functional_source_fixture import copy_trusted_protocol


@pytest.fixture
def trusted_source(tmp_path):
    root = tmp_path / 'trusted'
    copy_trusted_protocol(root)
    env = root / 'conf/env'
    env.mkdir(parents=True)
    (env / 'base.yaml').write_text('''template:
  mds_addr: mds.test:6900
  run_as_user: worker/password-do-not-display
  storage: {storage_type: s3, storage_env: backend}
  clients:
    - host: client.test
      client_count: 2
      mount_path: /mnt/original
  remote_caches:
    - host: cache.test
      remote_cache_count: 3
''')
    (env / 'child.yaml').write_text('env_Original:\n  base: template\n')
    (root / 'conf/storage.yaml').write_text('backend:\n  storage_type: s3\n  s3: {s3_sk: private-storage-key}\n')
    cases = root / 'testcases/basic_file_operation'
    cases.mkdir(parents=True)
    (cases / 'case.yaml').write_text('case_name: fixture\nsteps:\n  - include: steps.yaml\n')
    (cases / 'steps.yaml').write_text('steps: []\n')
    return root


def inspect(root, modules=None):
    from dingofs_platform.functional import source_bridge
    return source_bridge.inspect_source(root, 'env_Original', modules or {})


def test_real_protocol_preserves_names_complete_manifest_and_redacts(trusted_source):
    descriptor = inspect(trusted_source, {'basic_file_operation': ['testcases/basic_file_operation/case.yaml']})
    assert descriptor.env_name == 'env_Original'
    assert descriptor.client_count == 2 and descriptor.cache_count == 3
    assert descriptor.mds_addresses == ['mds.test:6900']
    assert {target.host for target in descriptor.targets} == {'mds.test', 'client.test', 'cache.test'}
    assert set(descriptor.source_manifest) == {
        'conf/env/base.yaml', 'conf/env/child.yaml', 'conf/storage.yaml',
        'testcases/basic_file_operation/case.yaml', 'testcases/basic_file_operation/steps.yaml',
    }
    assert descriptor.source_manifest['conf/env/base.yaml'] == hashlib.sha256(
        (trusted_source / 'conf/env/base.yaml').read_bytes()).hexdigest()
    assert 'password-do-not-display' not in descriptor.model_dump_json()
    assert 'private-storage-key' not in descriptor.model_dump_json()


@pytest.mark.parametrize('relative', ['conf/env/base.yaml', 'conf/storage.yaml', 'testcases/basic_file_operation/steps.yaml'])
def test_base_storage_and_include_changes_invalidate_digest(trusted_source, relative):
    selection = {'basic_file_operation': ['testcases/basic_file_operation/case.yaml']}
    before = inspect(trusted_source, selection)
    path = trusted_source / relative
    path.write_text(path.read_text() + '\n# revision\n')
    after = inspect(trusted_source, selection)
    assert before.digest != after.digest
    assert before.source_manifest[relative] != after.source_manifest[relative]


def test_missing_case_constraint_does_not_override_missing_environment_prerequisites(trusted_source):
    (trusted_source / 'conf/env/child.yaml').write_text('env_Original: {}\n')
    value = inspect(trusted_source, {'basic_file_operation': ['testcases/basic_file_operation/case.yaml']})
    assert not value.modules['basic_file_operation'].available
    assert value.modules['basic_file_operation'].reasons


@pytest.mark.parametrize('selection', [
    {'basic_file_operation': ['../private.yaml']},
    {'basic_file_operation': ['/tmp/private.yaml']},
])
def test_request_paths_cannot_escape_trusted_root(trusted_source, selection):
    with pytest.raises(ValueError, match='inspection request'):
        inspect(trusted_source, selection)


def test_symlink_source_escape_is_rejected(trusted_source, tmp_path):
    path = trusted_source / 'conf/env/base.yaml'
    outside = tmp_path / 'private.yaml'
    path.rename(outside)
    path.symlink_to(outside)
    value = inspect(trusted_source)
    assert value.issues and value.client_count is None
    assert 'private-storage-key' not in repr(value)


@pytest.mark.parametrize('operation', [
    "import socket; socket.socket()",
    "import subprocess; subprocess.run(['true'])",
    "open('forbidden-write', 'w').write('bad')",
])
def test_inspected_process_hard_denies_side_effects(trusted_source, operation):
    entry = trusted_source / 'src/test_runner/functional_contracts.py'
    entry.write_text(operation + '\n')
    with pytest.raises(ValueError, match='inspector failed'):
        inspect(trusted_source)
    assert not (trusted_source / 'forbidden-write').exists()


@pytest.mark.parametrize('script,match', [
    ("import sys; print('private-password', file=sys.stderr); raise SystemExit(2)", 'inspector failed'),
    ("print('private-password not JSON')", 'invalid inspector response'),
    ("print('{}')", 'invalid inspector response'),
])
def test_errors_are_sanitized(trusted_source, script, match):
    (trusted_source / 'src/test_runner/functional_contracts.py').write_text(script)
    with pytest.raises(ValueError, match=match) as error:
        inspect(trusted_source)
    assert 'private-password' not in str(error.value)


def test_timeout_is_enforced(trusted_source, monkeypatch):
    from dingofs_platform.functional import source_bridge
    monkeypatch.setattr(source_bridge, 'INSPECT_TIMEOUT_SECONDS', 0.1)
    (trusted_source / 'src/test_runner/functional_contracts.py').write_text('import time; time.sleep(10)\n')
    with pytest.raises(ValueError, match='timed out'):
        inspect(trusted_source)


@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
def test_output_is_bounded_while_child_is_running(trusted_source, monkeypatch, stream):
    from dingofs_platform.functional import source_bridge
    monkeypatch.setattr(source_bridge, 'MAX_OUTPUT_BYTES', 1024)
    (trusted_source / 'src/test_runner/functional_contracts.py').write_text(
        f"import sys\nwhile True: sys.{stream}.write('x' * 1024); sys.{stream}.flush()\n")
    with pytest.raises(ValueError, match='output limit'):
        inspect(trusted_source)


def test_descriptor_identity_and_manifest_are_validated(trusted_source, monkeypatch):
    from dingofs_platform.functional import source_bridge
    valid = inspect(trusted_source).model_dump()
    for mutation in ({'env_name': 'other'}, {'digest': '0' * 64}, {'source_manifest': {'../private': '0' * 64}}, {'programs': {'password': 'secret'}}):
        monkeypatch.setattr(source_bridge, '_run_inspector', lambda *args: json.dumps({**valid, **mutation}).encode())
        with pytest.raises(ValueError, match='invalid inspector response'):
            inspect(trusted_source)
