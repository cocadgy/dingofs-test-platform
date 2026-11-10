"""Release gates use real schema/source; no remote connections are permitted."""
from fastapi.testclient import TestClient
from sqlalchemy import text
import pytest

from dingofs_platform.app import create_app
from dingofs_platform.app import _check_guided_migration as actual_migration_check
from dingofs_platform.settings import Settings
from test_functional_preflight import ready, deny_real_ssh


@pytest.fixture(autouse=True)
def revision_marker(app, monkeypatch):
    monkeypatch.setattr('dingofs_platform.app._check_guided_migration', actual_migration_check)
    with app.state.engine.begin() as connection:
        connection.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)'))
        connection.execute(text("INSERT INTO alembic_version VALUES ('7b1c9e4a602d')"))
    yield
    with app.state.engine.begin() as connection:
        connection.execute(text('DROP TABLE IF EXISTS alembic_version'))


def test_approved_environment_flag_enables_creation(monkeypatch):
    monkeypatch.delenv('PLATFORM_FUNCTIONAL_GUIDED_ENABLED', raising=False)
    monkeypatch.setenv('PLATFORM_GUIDED_FUNCTIONAL_ENABLED', 'true')
    settings = Settings(database_url='postgresql+psycopg://localhost/local_test')
    assert settings.functional_guided_enabled


def test_default_off_keeps_ordinary_readiness_and_history(admin, app):
    assert admin.get('/health/ready').status_code == 200
    assert admin.get('/api/v1/functional/runs').status_code == 200


def test_enabled_missing_source_is_unready_and_cannot_offer_creation(admin, app, tmp_path):
    app.state.settings.functional_guided_enabled = True
    app.state.settings.functional_source_root = tmp_path / 'absent/testcases'
    assert admin.get('/health/ready').status_code == 503
    assert admin.get('/api/v1/functional/guided/metadata').status_code == 503
    assert admin.get('/api/v1/functional/runs').status_code == 200


def test_actual_source_contract_and_schema_make_enabled_service_ready(admin, app, ready):
    response = admin.get('/health/ready')
    assert response.status_code == 200, response.text
    assert response.json()['guided_functional'] == 'ready'
    assert ready[2].calls == []


def test_missing_migration_columns_reject_enabled_readiness(admin, app, ready):
    with app.state.engine.begin() as connection:
        connection.execute(text('ALTER TABLE functional_module_runs DROP COLUMN launch_attempted_at'))
    assert admin.get('/health/ready').status_code == 503


@pytest.mark.parametrize('statement', [
    'DROP TABLE alembic_version',
    "UPDATE alembic_version SET version_num = '2f6d6db8c141'",
])
def test_missing_or_old_migration_marker_cannot_enable_creation(admin, app, ready, statement):
    with app.state.engine.begin() as connection:
        connection.execute(text(statement))
    assert admin.get('/health/ready').status_code == 503
    assert admin.get('/api/v1/functional/guided/metadata').status_code == 503
    assert admin.get('/api/v1/functional/runs').status_code == 200


def test_v2_rerun_cannot_bypass_enabled_migration_gate(admin, app, ready):
    from test_functional_guided_api import body
    created = admin.post('/api/v1/functional/runs', json=body(app, ready))
    assert created.status_code == 202, created.text
    with app.state.engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '2f6d6db8c141'"))
    endpoint = '/api/v1/functional/runs/' + created.json()['id'] + '/rerun'
    response = admin.post(endpoint, json={'idempotency_key': 'rerun-readiness'})
    assert response.status_code == 503, response.text
    assert response.json()['code'] == 'guided_runtime_unavailable'
    # Legacy no-body reruns still reach their original authorization/lookup.
    assert admin.post('/api/v1/functional/runs/missing-legacy/rerun').status_code == 404


@pytest.mark.parametrize('by_profile', [False, True])
def test_legacy_predefined_cannot_probe_or_persist_before_migration_ready(admin, app, ready, by_profile):
    from sqlalchemy import func, select
    from dingofs_platform.functional.models import FunctionalPreflight
    spec = ready[0]
    payload = dict(name='legacy-readiness', cluster_id=spec.cluster_id,
                   selected={'quota': ['case.yaml']}, catalog_digest=spec.catalog_digest)
    payload.update({'environment_profile_id': ready[4]['id'],
                    'environment_profile_revision': ready[4]['revision']}
                   if by_profile else {'env_name': 'env_ready'})
    with app.state.engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '2f6d6db8c141'"))
    response = admin.post('/api/v1/functional/runs', json=payload)
    with app.state.session_factory() as db:
        token_count = db.scalar(select(func.count()).select_from(FunctionalPreflight))
    assert (response.status_code, len(ready[2].calls), token_count) == (503, 0, 0), response.text
    assert response.json()['code'] == 'guided_runtime_unavailable'


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('kind', ['custom', 'wizard'])
def test_legacy_custom_and_wizard_ignore_guided_migration_gate(admin, app, ready, enabled, kind):
    spec = ready[0]
    storage = admin.post('/api/v1/storage-profiles', json={
        'name': 'legacy-storage', 'storage_type': 's3', 'enabled': True,
        'parameters': {'s3_ak': 'fixture', 's3_sk': 'fixture',
                       's3_endpoint': 'http://store', 's3_bucketname': 'bucket'}})
    assert storage.status_code == 201, storage.text
    configuration = {'machine_id': ready[3]['id'], 'storage_profile_id': storage.json()['id'],
                     'settings': {'mount_root': '/tmp/legacy', 'fs_prefix': 'legacy'}}
    payload = dict(name='legacy', cluster_id=spec.cluster_id,
                   selected={'quota': ['case.yaml']}, catalog_digest=spec.catalog_digest)
    if kind == 'custom':
        profile = admin.post('/api/v1/functional/environments', json={
            **configuration, 'name': 'legacy-custom', 'cluster_id': spec.cluster_id, 'enabled': True})
        assert profile.status_code == 201, profile.text
        payload.update(environment_profile_id=profile.json()['id'],
                       environment_profile_revision=profile.json()['revision'])
    else:
        payload['wizard'] = configuration
    app.state.settings.functional_guided_enabled = enabled
    with app.state.engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '2f6d6db8c141'"))
    response = admin.post('/api/v1/functional/runs', json=payload)
    assert response.status_code == 202, response.text
    assert response.json()['snapshot']['environment_profile_snapshot']['kind'] == 'custom'
    assert ready[2].calls == []
    assert admin.get('/api/v1/functional/runs/' + response.json()['id']).status_code == 200


def test_functional_worker_runs_with_creation_disabled_and_performance_disabled(app, monkeypatch):
    settings = app.state.settings.model_copy(update={'functional_worker_enabled': True})
    instance = create_app(settings)
    calls = []
    monkeypatch.setattr(instance.state.functional_manager, 'start', lambda: calls.append('functional'))
    monkeypatch.setattr(instance.state.performance_manager, 'start', lambda: calls.append('performance'))
    with TestClient(instance):
        assert calls == ['functional']
    instance.state.engine.dispose()


def test_broken_optional_source_does_not_prevent_history_service_startup(app, tmp_path):
    root = tmp_path / 'broken-source'
    (root / 'conf/env').mkdir(parents=True)
    (root / 'conf/env/broken.yaml').write_text('env_broken: {}\n')
    settings = app.state.settings.model_copy(update={'functional_source_root': root / 'testcases'})
    instance = create_app(settings)
    try:
        with TestClient(instance) as client:
            assert client.get('/health/ready').status_code == 200
            instance.state.settings.functional_guided_enabled = True
            assert client.get('/health/ready').status_code == 503
            assert client.get('/health/live').status_code == 200
    finally:
        instance.state.engine.dispose()


def test_actual_upgrade_downgrade_upgrade_changes_enabled_readiness(app, ready):
    """Use real Alembic upgrades in a fresh schema of the exclusive E2E DB."""
    from pathlib import Path
    from uuid import uuid4
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    assert app.state.engine.url.database.endswith('_test')
    assert app.state.engine.url.host in ('127.0.0.1', 'localhost')
    schema = 'guided_release_' + uuid4().hex
    with app.state.engine.begin() as connection:
        connection.execute(text('CREATE SCHEMA ' + schema))
    engine = create_engine(app.state.engine.url, connect_args={'options': '-csearch_path=' + schema})
    instance = create_app(app.state.settings)
    instance.state.engine.dispose()
    instance.state.engine = engine
    config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    try:
        with engine.connect() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
        client = TestClient(instance)
        assert client.get('/health/ready').json() == {'status': 'ok', 'guided_functional': 'ready'}
        with engine.connect() as connection:
            config.attributes['connection'] = connection
            command.downgrade(config, '2f6d6db8c141')
        assert client.get('/health/ready').status_code == 503
        with engine.connect() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
        assert client.get('/health/ready').status_code == 200
        client.close()
    finally:
        engine.dispose()
        with app.state.engine.begin() as connection:
            connection.execute(text('DROP SCHEMA ' + schema + ' CASCADE'))
