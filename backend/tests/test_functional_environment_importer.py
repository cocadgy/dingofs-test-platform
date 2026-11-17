from pathlib import Path
import pytest
from dingofs_platform.functional.environments.importer import scan_predefined


def test_scan_predefined_resolves_base_without_exposing_secret(tmp_path):
    root = tmp_path / 'conf' / 'env'
    root.mkdir(parents=True)
    (root / 'a.yaml').write_text('''env_base:
  mds_addr: 10.0.0.1:6900
  run_as_user: user/secret123
  storage:
    storage_type: s3
    storage_env: minio
  clients:
    - host: node-a
      mount_path: /mnt/tests
env_child:
  base: env_base
  clients:
    - mount_path: /mnt/new
''')
    records = {item.key: item for item in scan_predefined(root)}
    assert set(records) == {'env_base', 'env_child'}
    assert records['env_child'].mds_addresses == ('10.0.0.1:6900',)
    assert records['env_child'].client_hosts == ('node-a',)
    assert records['env_child'].storage_type == 's3'
    assert records['env_child'].source_file == 'a.yaml'
    assert 'secret123' not in repr(records)
    assert records['env_child'].source_digest != records['env_base'].source_digest


def test_scan_rejects_cycle_duplicate_and_missing_base(tmp_path):
    root = tmp_path / 'env'; root.mkdir()
    (root / 'a.yaml').write_text('env_a:\n  base: env_b\nenv_b:\n  base: env_a\n')
    with pytest.raises(ValueError, match='cycle'):
        scan_predefined(root)
    (root / 'a.yaml').write_text('env_a: {}\n')
    (root / 'b.yaml').write_text('env_a: {}\n')
    with pytest.raises(ValueError, match='Duplicate'):
        scan_predefined(root)
    (root / 'b.yaml').write_text('env_b:\n  base: env_missing\n')
    with pytest.raises(ValueError, match='missing'):
        scan_predefined(root)


def test_real_source_has_all_predefined_entries():
    root = Path('/mnt/disk5/daigy/dingofs-testsuite-tool/dingofs-integration-test/conf/env')
    if not root.exists():
        pytest.skip('source checkout unavailable in this environment')
    assert len(list(root.glob('*.yaml'))) == 41
    assert len(scan_predefined(root)) == 100


def test_preset_summary_counts_cache_members(tmp_path):
    (tmp_path/'a.yaml').write_text('env_a:\n  remote_caches:\n    - remote_cache_count: 3\n    - remote_cache_count: 2\n')
    assert scan_predefined(tmp_path)[0].cache_count == 5
