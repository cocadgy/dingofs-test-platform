from dataclasses import asdict

import pytest
from ruamel.yaml import YAML

from dingofs_platform.functional.environments.importer import scan_predefined
from test_functional_source_bridge import trusted_source


def records(source):
    return {item.key: item for item in scan_predefined(source / 'conf/env')}


def test_scan_preserves_framework_descriptor_without_secrets(trusted_source):
    values = records(trusted_source)
    child = values['env_Original']
    assert child.mds_addresses == ('mds.test:6900',)
    assert child.client_hosts == ('client.test',)
    assert child.storage_type == 's3'
    assert child.client_count == 2 and child.cache_count == 3
    assert child.base == 'template' and child.source_file == 'child.yaml'
    assert values['template'].template and not values['template'].runnable
    assert child.runnable
    assert child.descriptor.env_name == child.key
    assert child.source_digest == child.descriptor.digest
    assert set(child.descriptor.source_manifest) == {
        'conf/env/base.yaml', 'conf/env/child.yaml', 'conf/storage.yaml',
    }
    assert child.descriptor.modules == {}  # Source-only, no compatibility claim.
    assert 'password-do-not-display' not in repr(asdict(child))
    assert 'private-storage-key' not in repr(asdict(child))


def test_temporary_source_enumerates_all_top_level_environment_keys(trusted_source):
    root = trusted_source / 'conf/env'
    (root / 'extra.yaml').write_text('env_second: {}\nenv_third: {}\n')
    loader = YAML(typ='safe')
    enumerated = {(path.name, key) for path in root.glob('*.yaml') for key in loader.load(path.read_text())}
    actual = {(item.source_file, item.key) for item in scan_predefined(root)}
    assert actual == enumerated
    assert len(actual) == 4


def test_relative_server_configured_root_is_supported(trusted_source, monkeypatch):
    from pathlib import Path
    monkeypatch.chdir(trusted_source)
    assert {item.key for item in scan_predefined(Path('conf/env'))} == {'template', 'env_Original'}


@pytest.mark.parametrize('yaml,reason', [
    ('env_Original:\n  base: absent\n', 'missing'),
    ('env_Original:\n  base: cycle\ncycle:\n  base: env_Original\n', 'cycle'),
    ('env_Original:\n  clients: bad\n', 'resolved'),
])
def test_invalid_resolution_is_explicit_and_counts_remain_unknown(trusted_source, yaml, reason):
    (trusted_source / 'conf/env/child.yaml').write_text(yaml)
    child = records(trusted_source)['env_Original']
    assert not child.runnable
    assert reason in child.issue
    assert child.client_count is None and child.cache_count is None


def test_incomplete_environment_has_explicit_reason(trusted_source):
    (trusted_source / 'conf/env/child.yaml').write_text('env_Original: {}\n')
    child = records(trusted_source)['env_Original']
    assert not child.runnable and child.issue


def test_duplicate_names_are_rejected(trusted_source):
    (trusted_source / 'conf/env/duplicate.yaml').write_text('env_Original: {}\n')
    with pytest.raises(ValueError, match='duplicate environment'):
        records(trusted_source)


def test_malformed_yaml_error_never_quotes_source_credentials(trusted_source):
    (trusted_source / 'conf/env/child.yaml').write_text('env_Original: [private-password\n')
    with pytest.raises(ValueError, match='invalid environment source') as error:
        records(trusted_source)
    assert 'private-password' not in str(error.value)


def test_symlink_escape_is_explicit_not_silently_skipped(trusted_source, tmp_path):
    outside = tmp_path / 'outside.yaml'
    outside.write_text('env_external: {}\n')
    (trusted_source / 'conf/env/escape.yaml').symlink_to(outside)
    with pytest.raises(ValueError, match='environment source'):
        records(trusted_source)


def test_disappeared_base_disables_dependent_preset(trusted_source):
    before = records(trusted_source)['env_Original']
    (trusted_source / 'conf/env/base.yaml').unlink()
    after = records(trusted_source)['env_Original']
    assert before.runnable and not after.runnable
    assert 'missing' in after.issue
    assert before.source_digest != after.source_digest


def test_expanded_hosts_counts_come_from_framework(trusted_source):
    (trusted_source / 'conf/env/child.yaml').write_text('''env_Original:
  base: template
  hosts:
    - host: host-format.test
      client_count: 4
      remote_cache_count: 5
''')
    child = records(trusted_source)['env_Original']
    assert child.client_count == 4 and child.cache_count == 5
    assert child.client_hosts == ('host-format.test',)


def test_sync_persists_descriptor_drift_and_disappearance_without_raw_settings(app, trusted_source):
    from sqlalchemy import select
    from dingofs_platform.functional.environments.models import FunctionalEnvironmentProfile as Profile
    from dingofs_platform.functional.environments.service import sync_predefined

    root = trusted_source / 'conf/env'
    with app.state.session_factory.begin() as db:
        sync_predefined(db, root)
    with app.state.session_factory.begin() as db:
        child = db.scalar(select(Profile).where(Profile.source_key == 'env_Original'))
        assert child.settings == {}
        assert child.display['descriptor']['env_name'] == 'env_Original'
        assert len(child.display['descriptor']['source_manifest']) == 3
        assert 'password-do-not-display' not in repr(child.display)
        assert 'private-storage-key' not in repr(child.display)
        original_digest, revision = child.source_digest, child.revision
        assert sync_predefined(db, root)['updated'] == 0
        base = root / 'base.yaml'
        base.write_text(base.read_text() + '\n# changed base\n')
        sync_predefined(db, root)
        assert child.source_digest != original_digest
        assert child.revision == revision + 1
        assert child.display['descriptor']['digest'] == child.source_digest
        (root / 'child.yaml').unlink()
        sync_predefined(db, root)
        assert not child.enabled and child.validation == 'source_missing'


def test_sync_template_change_updates_state_without_forging_source_digest(app, trusted_source):
    from sqlalchemy import select
    from dingofs_platform.functional.environments.models import FunctionalEnvironmentProfile as Profile
    from dingofs_platform.functional.environments.service import sync_predefined

    root = trusted_source / 'conf/env'
    child_path = root / 'child.yaml'
    child_text = child_path.read_text()
    child_path.unlink()
    with app.state.session_factory.begin() as db:
        sync_predefined(db, root)
        base = db.scalar(select(Profile).where(Profile.source_key == 'template'))
        assert base.enabled and not base.display['template']
        digest, revision = base.source_digest, base.revision
        child_path.write_text(child_text)
        sync_predefined(db, root)
        assert not base.enabled and base.validation == 'template'
        assert base.revision == revision + 1 and base.source_digest == digest
        child_path.unlink()
        sync_predefined(db, root)
        assert base.enabled and base.validation == 'needs_validation'
        assert base.revision == revision + 2 and base.source_digest == digest


def test_sync_restored_identical_source_requires_validation(app, trusted_source):
    from sqlalchemy import select
    from dingofs_platform.functional.environments.models import FunctionalEnvironmentProfile as Profile
    from dingofs_platform.functional.environments.service import sync_predefined

    root = trusted_source / 'conf/env'
    path = root / 'child.yaml'
    original = path.read_text()
    with app.state.session_factory.begin() as db:
        sync_predefined(db, root)
        child = db.scalar(select(Profile).where(Profile.source_key == 'env_Original'))
        digest, revision = child.source_digest, child.revision
        path.unlink()
        sync_predefined(db, root)
        assert not child.enabled and child.validation == 'source_missing'
        assert child.revision == revision + 1
        sync_predefined(db, root)
        assert child.revision == revision + 1
        path.write_text(original)
        sync_predefined(db, root)
        assert child.enabled and child.validation == 'needs_validation'
        assert child.source_digest == digest and child.revision == revision + 2
