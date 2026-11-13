from types import SimpleNamespace

import pytest

from dingofs_platform.errors import Problem
from dingofs_platform.functional.environments import importer
from dingofs_platform.functional.environments.validation import validate_target
from test_functional_source_bridge import trusted_source


def selection(source):
    record = next(x for x in importer.scan_predefined(source / 'conf/env') if x.key == 'env_Original')
    return (
        SimpleNamespace(enabled=True, deleted=False, source_kind='predefined',
                        source_key=record.key, source_file=record.source_file,
                        source_digest=record.source_digest),
        SimpleNamespace(status_snapshot={'mds_addresses': ['mds.test:6900']}),
        SimpleNamespace(address='client.test', name='client', aliases=[]),
    )


def test_target_validation_resolves_only_selected_environment(trusted_source, monkeypatch):
    args = selection(trusted_source)
    for i in range(30):
        (trusted_source / 'conf/env' / f'unrelated{i}.yaml').write_text(f'unrelated{i}: {{}}\n')
    original = importer.inspect_source
    inspected = []
    def inspect(root, key, modules):
        inspected.append(key)
        return original(root, key, modules)
    monkeypatch.setattr(importer, 'inspect_source', inspect)
    validate_target(*args, trusted_source / 'testcases', {})
    assert inspected == ['env_Original']


def test_target_validation_still_rejects_changed_inherited_source(trusted_source):
    args = selection(trusted_source)
    base = trusted_source / 'conf/env/base.yaml'
    base.write_text(base.read_text() + '\n# updated inherited environment\n')
    with pytest.raises(Problem) as error:
        validate_target(*args, trusted_source / 'testcases', {})
    assert error.value.code == 'environment_source_changed'


def test_target_validation_still_rejects_missing_selection(trusted_source):
    args = selection(trusted_source)
    (trusted_source / 'conf/env/child.yaml').unlink()
    with pytest.raises(Problem) as error:
        validate_target(*args, trusted_source / 'testcases', {})
    assert error.value.code == 'environment_source_changed'
