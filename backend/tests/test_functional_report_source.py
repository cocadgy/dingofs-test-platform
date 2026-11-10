"""Private source credential extraction through the actual bounded parser bridge."""
import hashlib
import os
from pathlib import Path
import shutil

import pytest

from functional_source_fixture import copy_trusted_protocol
from dingofs_platform.errors import Problem


def source(tmp_path):
    root = tmp_path / 'source'
    copy_trusted_protocol(root)
    relative = 'src/test_runner/functional_redaction.py'
    shutil.copyfile(Path(os.environ['FUNCTIONAL_CONTRACTS_TEST_ROOT']) / relative, root / relative)
    (root / 'conf/env').mkdir(parents=True)
    (root / 'conf/env/test.yaml').write_text('''env_report:
  run_as_user: test/secret-for-report
  mds_addr: node:6900
  storage: {storage_type: s3, storage_env: store}
''')
    (root / 'conf/storage.yaml').write_text('store:\n  s3: {s3_ak: sample-ak, s3_sk: sample-sk, s3_endpoint: http://store, s3_bucketname: bucket}\n')
    manifest = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob('*') if p.is_file()}
    return root, manifest


def test_report_secrets_require_exact_source_and_never_enter_error(tmp_path, caplog):
    from dingofs_platform.functional.reports import load_report_secrets
    root, manifest = source(tmp_path)
    secrets = load_report_secrets(root, 'env_report', manifest)
    assert {'secret-for-report', 'sample-ak', 'sample-sk'} <= set(secrets)
    (root / 'conf/storage.yaml').write_text('changed-source-secret')
    with pytest.raises(Problem) as exc:
        load_report_secrets(root, 'env_report', manifest)
    assert exc.value.status == 503
    assert 'secret' not in str(exc.value.details) and 'changed-source-secret' not in caplog.text


def test_report_refuses_missing_original_source(tmp_path):
    from dingofs_platform.functional.reports import load_report_secrets
    root, manifest = source(tmp_path)
    (root / 'conf/env/test.yaml').unlink()
    with pytest.raises(Problem) as exc:
        load_report_secrets(root, 'env_report', manifest)
    assert exc.value.status == 503


def test_report_refuses_added_unpinned_parser_code(tmp_path):
    from dingofs_platform.functional.reports import load_report_secrets
    root, manifest = source(tmp_path)
    (root / 'src/config/new_runtime.py').write_text('unexpected = True\n')
    with pytest.raises(Problem) as exc:
        load_report_secrets(root, 'env_report', manifest)
    assert exc.value.status == 503
