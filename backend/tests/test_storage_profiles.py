"""Shared storage credentials stay private and operations use an immutable snapshot."""

import json
import shlex
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from conftest import linked
from dingofs_platform.audit.models import AuditEvent
from dingofs_platform.clusters.transport import (
    AuthenticationRequired,
    ClusterCommandResult,
    ExecutionIdentity,
)
from dingofs_platform.inventory.credentials import decrypt_password
from dingofs_platform.resources.models import ResourceOperation


URL = "/api/v1/storage-profiles"
S3 = {
    "s3_ak": "profile-access-secret",
    "s3_sk": "profile-private-secret ' $(echo nope)",
    "s3_endpoint": "http://object.test:9000",
    "s3_bucketname": "integration",
}
RADOS = {
    "rados_username": "client.integration",
    "rados_key": "rados-private-secret",
    "rados_mon": "10.0.0.1:6789,10.0.0.2:6789",
    "rados_poolname": "integration",
    "rados_clustername": "ceph",
}


def body(storage_type="s3", **changes):
    return {
        "name": "shared-storage",
        "storage_type": storage_type,
        "description": "集成测试后端",
        "enabled": True,
        "parameters": dict(S3 if storage_type == "s3" else RADOS),
        **changes,
    }


@pytest.fixture
def storage(admin, app):
    app.state.settings.credential_encryption_key = Fernet.generate_key().decode()
    return admin


def add(client, **changes):
    response = client.post(URL, json=body(**changes))
    assert response.status_code == 201, response.text
    return response.json()


def login(client, username):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "test-password-123"},
    )
    assert response.status_code == 200
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response.json()["id"]


def operation(client, cluster, profile, **changes):
    payload = {
        "base_revision": cluster["revision"],
        "request_id": str(uuid4()),
        "action": "fs.create",
        "parameters": {
            "fs_name": "from-profile",
            "partition_type": "hash",
            "storage_profile_id": profile["id"],
            "storage_profile_revision": profile["revision"],
        },
        "confirmed": True,
        **changes,
    }
    return client.post(
        "/api/v1/clusters/" + cluster["id"] + "/resource-operations", json=payload
    )


def test_profiles_encrypt_credentials_and_never_publish_them(storage, app):
    record = add(storage)
    assert record["has_secrets"] and record["can_manage"]
    assert record["parameters"] == {
        "s3_endpoint": S3["s3_endpoint"], "s3_bucketname": "integration"
    }
    assert record["revision"] == 1 and record["created_at"] and record["updated_at"]
    listing = storage.get(URL)
    assert listing.status_code == 200 and listing.json() == [record]
    from dingofs_platform.storage.models import StorageProfile

    with app.state.session_factory() as db:
        row = db.get(StorageProfile, record["id"])
        stored = json.dumps({column.name: getattr(row, column.name) for column in row.__table__.columns}, default=str)
        encrypted = row.secret_ciphertext
        assert json.loads(decrypt_password(encrypted, app.state.settings.credential_encryption_key)) == {
            "s3_ak": S3["s3_ak"], "s3_sk": S3["s3_sk"]
        }
        audits = json.dumps([event.detail for event in db.scalars(select(AuditEvent))])
    for text in (listing.text, stored, audits):
        assert S3["s3_ak"] not in text and S3["s3_sk"] not in text
    assert encrypted not in listing.text


@pytest.mark.parametrize("storage_type", ["s3", "rados"])
def test_profile_update_preserves_omitted_or_empty_secrets(storage, app, storage_type):
    record = add(storage, storage_type=storage_type)
    public = record["parameters"]
    secret_key = "s3_sk" if storage_type == "s3" else "rados_key"
    edited = storage.put(URL + "/" + record["id"], json=body(
        storage_type, name="renamed", revision=1,
        parameters={**public, secret_key: ""}, enabled=False,
    ))
    assert edited.status_code == 200, edited.text
    assert edited.json()["revision"] == 2 and edited.json()["has_secrets"]
    assert not edited.json()["enabled"]
    from dingofs_platform.storage.models import StorageProfile

    with app.state.session_factory() as db:
        value = json.loads(decrypt_password(db.get(StorageProfile, record["id"]).secret_ciphertext, app.state.settings.credential_encryption_key))
        assert value[secret_key] == (S3 if storage_type == "s3" else RADOS)[secret_key]
    rotated = storage.put(URL + "/" + record["id"], json=body(
        storage_type, name="renamed", revision=2,
        parameters={**public, secret_key: "new-private-value"},
    ))
    assert rotated.status_code == 200, rotated.text
    with app.state.session_factory() as db:
        value = json.loads(decrypt_password(db.get(StorageProfile, record["id"]).secret_ciphertext, app.state.settings.credential_encryption_key))
        assert value[secret_key] == "new-private-value"


def test_profiles_are_shared_but_only_creator_or_admin_can_mutate(storage):
    record = add(storage)
    member_id = login(storage, "member")
    listed = storage.get(URL).json()[0]
    assert listed["id"] == record["id"] and not listed["can_manage"]
    assert storage.put(URL + "/" + record["id"], json=body(revision=1)).status_code == 403
    assert storage.delete(URL + "/" + record["id"], params={"revision": 1}).status_code == 403
    own = add(storage, name="member-storage")
    assert own["creator_id"] == member_id and own["can_manage"]
    assert storage.put(URL + "/" + own["id"], json=body(name="member-edited", revision=1)).status_code == 200
    login(storage, "admin")
    assert storage.delete(URL + "/" + own["id"], params={"revision": 2}).status_code == 204
    assert [row["id"] for row in storage.get(URL).json()] == [record["id"]]


def test_profile_revision_conflicts_and_type_changes_are_rejected(storage):
    record = add(storage)
    url = URL + "/" + record["id"]
    assert storage.put(url, json=body(revision=2)).status_code == 409
    assert storage.delete(url, params={"revision": 2}).status_code == 409
    assert storage.put(url, json=body("rados", revision=1)).status_code == 422
    assert storage.delete(url, params={"revision": 1}).status_code == 204
    assert storage.get(URL).json() == []
    assert storage.put(url, json=body(revision=2)).status_code == 404
    assert storage.delete(url, params={"revision": 2}).status_code == 404


@pytest.mark.parametrize("changes", [
    {"parameters": {"s3_endpoint": "http://host", "s3_bucketname": "bucket"}},
    {"parameters": {**S3, "s3_sk": ""}},
    {"parameters": {**S3, "s3_endpoint": "endpoint\nunsafe"}},
    {"parameters": {**S3, "rados_key": "secret-extra"}},
    {"parameters": {**S3, "s3_endpoint": 12}},
    {"name": " "}, {"storage_type": "file"}, {"enabled": "true"},
    {"unexpected": "secret-extra"},
])
def test_profile_input_validation_does_not_echo_secrets(storage, changes):
    response = storage.post(URL, json=body(**changes))
    assert response.status_code == 422, response.text
    assert "secret-extra" not in response.text and S3["s3_ak"] not in response.text
    assert storage.get(URL).json() == []


def test_profiles_require_login_and_csrf(client):
    assert client.get(URL).status_code == 401
    login(client, "member")
    del client.headers["X-CSRF-Token"]
    assert client.post(URL, json=body()).status_code == 403


def test_profile_secret_requires_encryption_key(admin):
    response = admin.post(URL, json=body())
    assert response.status_code == 503, response.text
    assert S3["s3_ak"] not in response.text
    assert admin.get(URL).json() == []


@pytest.mark.parametrize("storage_type", ["s3", "rados"])
def test_fs_create_snapshots_profile_credentials_and_replay_survives_deletion(storage, app, storage_type):
    _, cluster, _ = linked(storage)
    record = add(storage, storage_type=storage_type)
    commands = []

    def transport(config, cmd, **kwargs):
        request = json.loads(shlex.split(cmd.resource_script)[3])
        commands.append(request["commands"][0])
        if kwargs["password"] != "switch-password":
            raise AuthenticationRequired("test")
        return ClusterCommandResult(
            ExecutionIdentity("test", "/home/test", "/bin/dingo"),
            json.dumps({"returncode": 0, "data": {"name": "from-profile"}}), "", 0,
        )

    app.state.resource_transport = transport
    request_id = str(uuid4())
    started = operation(storage, cluster, record, request_id=request_id)
    assert started.status_code == 202, started.text
    url = "/api/v1/resource-operations/" + started.json()["id"]
    pending = storage.get(url).json()
    assert pending["state"] == "needs_password", pending
    assert pending["payload"]["storage_profile_id"] == record["id"]
    assert pending["payload"]["source_name"] == "shared-storage"
    with app.state.session_factory() as db:
        row = db.get(ResourceOperation, started.json()["id"])
        stored = json.dumps([row.parameters, row.steps])
        old_secrets = json.loads(decrypt_password(row.secret_ciphertext, app.state.settings.credential_encryption_key))
        assert all(value not in stored for value in old_secrets.values())
    public = record["parameters"]
    secret_key = "s3_sk" if storage_type == "s3" else "rados_key"
    endpoint_key = "s3_endpoint" if storage_type == "s3" else "rados_mon"
    assert storage.put(URL + "/" + record["id"], json=body(storage_type,
        revision=1, name="renamed-profile",
        parameters={**public, secret_key: "rotated-profile-secret", endpoint_key: "changed-endpoint"},
        enabled=False,
    )).status_code == 200
    assert storage.delete(URL + "/" + record["id"], params={"revision": 2}).status_code == 204
    retry = operation(storage, cluster, record, request_id=request_id)
    assert retry.status_code == 202 and retry.json()["id"] == started.json()["id"]
    response = storage.post(url + "/authenticate", json={"challenge": pending["challenge"], "password": "switch-password"})
    assert response.status_code == 200, response.text
    finished = storage.get(url).json()
    assert finished["state"] == "succeeded", finished
    flag = "--s3.sk" if storage_type == "s3" else "--rados.key"
    expected = (S3 if storage_type == "s3" else RADOS)[secret_key]
    assert commands[-1][commands[-1].index(flag) + 1] == expected
    assert "rotated-profile-secret" not in commands[-1]
    endpoint_flag = "--s3.endpoint" if storage_type == "s3" else "--rados.mon"
    assert commands[-1][commands[-1].index(endpoint_flag) + 1] == public[endpoint_key]
    assert finished["payload"]["source_name"] == "shared-storage"
    with app.state.session_factory() as db:
        assert db.get(ResourceOperation, started.json()["id"]).secret_ciphertext is None
    assert operation(storage, cluster, record).status_code == 422


@pytest.mark.parametrize("condition", ["disabled", "stale", "deleted", "missing"])
def test_fs_create_rejects_unavailable_profile_before_ssh(storage, app, condition):
    _, cluster, _ = linked(storage)
    record = add(storage)
    if condition == "disabled":
        changed = storage.put(URL + "/" + record["id"], json=body(revision=1, enabled=False))
        record = changed.json()
    elif condition == "stale":
        assert storage.put(URL + "/" + record["id"], json=body(revision=1)).status_code == 200
    elif condition == "deleted":
        assert storage.delete(URL + "/" + record["id"], params={"revision": 1}).status_code == 204
    else:
        record["id"] = str(uuid4())
    app.state.resource_transport = lambda *args, **kwargs: pytest.fail("unavailable profile must not contact SSH")
    response = operation(storage, cluster, record)
    assert response.status_code == (409 if condition == "stale" else 422), response.text
    with app.state.session_factory() as db:
        assert db.scalar(select(ResourceOperation)) is None


@pytest.mark.parametrize("extra", [
    {"s3_endpoint": "http://override"}, {"storage_type": "s3"}, {"s3_sk": "override"},
    {"rados_mon": ""}, {"storage_profile_revision": 0}, {"storage_profile_revision": True},
])
def test_profile_operations_reject_overrides_and_invalid_revisions(storage, app, extra):
    _, cluster, _ = linked(storage)
    record = add(storage)
    app.state.resource_transport = lambda *args, **kwargs: pytest.fail("invalid request must not contact SSH")
    response = operation(storage, cluster, record, parameters={
        "fs_name": "data", "storage_profile_id": record["id"],
        "storage_profile_revision": 1, **extra,
    })
    assert response.status_code == 422, response.text


def test_resource_inventory_includes_shared_profiles_and_profile_selector_fields(storage):
    _, cluster, _ = linked(storage)
    record = add(storage)
    login(storage, "member")
    inventory = storage.get("/api/v1/clusters/" + cluster["id"] + "/resources")
    assert inventory.status_code == 200, inventory.text
    snapshot = inventory.json()
    assert snapshot["storage_profiles"][0]["id"] == record["id"]
    assert not snapshot["storage_profiles"][0]["can_manage"]
    create = next(item for item in snapshot["catalog"] if item["action"] == "fs.create")
    fields = {field["key"]: field for field in create["fields"]}
    assert fields["storage_profile_id"]["type"] == "text"
    assert fields["storage_profile_revision"]["type"] == "number"
    assert not fields["storage_profile_id"]["required"]
    assert S3["s3_ak"] not in inventory.text and S3["s3_sk"] not in inventory.text


def test_profile_can_replace_all_credentials_after_encryption_key_changes(storage, app):
    record = add(storage)
    app.state.settings.credential_encryption_key = Fernet.generate_key().decode()
    response = storage.put(URL + "/" + record["id"], json=body(
        revision=1, parameters={**S3, "s3_ak": "replacement-ak", "s3_sk": "replacement-sk"},
    ))
    assert response.status_code == 200, response.text
    from dingofs_platform.storage.models import StorageProfile

    with app.state.session_factory() as db:
        saved = db.get(StorageProfile, record["id"])
        assert json.loads(decrypt_password(saved.secret_ciphertext, app.state.settings.credential_encryption_key)) == {
            "s3_ak": "replacement-ak", "s3_sk": "replacement-sk",
        }


def test_member_can_create_filesystem_using_another_users_shared_profile(storage, app):
    from conftest import machine, register_cluster

    record = add(storage)
    login(storage, "member")
    target = machine(storage, name="member-node")
    cluster = register_cluster(storage, target)
    executed = []

    def transport(config, cmd, **kwargs):
        executed.append(json.loads(shlex.split(cmd.resource_script)[3])["commands"][0])
        return ClusterCommandResult(
            ExecutionIdentity("test", "/home/test", "/bin/dingo"),
            json.dumps({"returncode": 0, "data": {"name": "from-profile"}}), "", 0,
        )

    app.state.resource_transport = transport
    response = operation(storage, cluster, record)
    assert response.status_code == 202, response.text
    completed = storage.get("/api/v1/resource-operations/" + response.json()["id"]).json()
    assert completed["state"] == "succeeded", completed
    assert executed[0][executed[0].index("--s3.sk") + 1] == S3["s3_sk"]


def test_profile_name_can_be_reused_after_deletion(storage):
    first = add(storage)
    duplicate = storage.post(URL, json=body())
    assert duplicate.status_code == 409
    assert storage.delete(URL + "/" + first["id"], params={"revision": 1}).status_code == 204
    replacement = add(storage)
    assert replacement["id"] != first["id"]
