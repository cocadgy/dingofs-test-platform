import json
from contextlib import contextmanager
from datetime import timedelta
from conftest import linked
from test_resource_api import runner, begin, member
from dingofs_platform.clusters.transport import ClusterCommandResult, ExecutionIdentity
from dingofs_platform.resources.models import ResourceOperation
from dingofs_platform.resources.views import now
from dingofs_platform.resources import cache_images, cache_transfer

DIGEST = "sha256:" + "a" * 64


def test_same_tag_is_prepared_once_and_long_download_plan_remains_consumable(admin, app, runner, monkeypatch):
    machine, cluster, _ = linked(admin)
    downloads, uploads = [], []
    artifact = {"path": "/platform/dingo-cache", "sha256": "b" * 64, "digest": DIGEST}
    def prepare(digest, root, cancelled, deadline):
        downloads.append(digest)
        assert not cancelled()
        return artifact
    @contextmanager
    def upload(config, value, cancelled, deadline):
        uploads.append(value["digest"])
        yield {"path": "/tmp/upload/dingo-cache", "sha256": value["sha256"]}
    monkeypatch.setattr(cache_images, "ensure_cached", prepare)
    monkeypatch.setattr(cache_transfer, "upload_binary", upload)
    def transport(config, cmd, **kwargs):
        req = json.loads(cmd.resource_script)
        runner.append(req)
        record = req["record"]
        info = {"path": "/home/test/.local/share/dingofs-platform/cache-binaries/abc/dingo-cache",
                "sha256": "b" * 64, "version": "main-fe4384a", "digest": DIGEST, "tag": "latest"}
        return ClusterCommandResult(ExecutionIdentity(cmd.target_user, "/home/test", "/bin/dingo"),
            json.dumps({"state": "planned" if req["action"] == "cache.plan" else "running", "returncode": 0,
                        "data": {"effective_port": record["listen_port"], "member": {**record, "binary_info": info}}}), "", 0)
    app.state.resource_transport = transport
    response = begin(admin, cluster, "cache.plan", {"group_name": "tag-cache", "members": [
        {**member(machine["id"], 21000 + i), "binary_source": "tag", "binary_tag": "latest", "binary_digest": DIGEST}
        for i in range(2)]})
    assert response.status_code == 202, response.text
    plan = admin.get("/api/v1/resource-operations/" + response.json()["id"]).json()
    assert plan["state"] == "succeeded", plan
    assert downloads == [DIGEST]
    assert uploads == [DIGEST]
    assert runner[0]["record"]["binary_upload"]["path"] == "/tmp/upload/dingo-cache"
    assert runner[1]["record"]["binary_upload"]["path"] == ""
    with app.state.session_factory.begin() as db:
        db.get(ResourceOperation, plan["id"]).created_at = now() - timedelta(minutes=15)
    created = begin(admin, cluster, "cache.create", {"plan_id": plan["id"]})
    assert created.status_code == 202, created.text
    final = admin.get("/api/v1/resource-operations/" + created.json()["id"]).json()
    assert final["state"] == "succeeded", final
    assert all(req["record"]["binary_digest"] == DIGEST for req in runner)


def test_download_failure_is_visible_and_never_contacts_a_target(admin, app, runner, monkeypatch):
    machine, cluster, _ = linked(admin)
    def fail(*args):
        raise ValueError("所选 TAG 不包含 dingo-cache")
    monkeypatch.setattr(cache_images, "ensure_cached", fail)
    response = begin(admin, cluster, "cache.plan", {"group_name": "bad-tag", "members": [
        {**member(machine["id"], 21000), "binary_source": "tag", "binary_tag": "old", "binary_digest": DIGEST}]})
    result = admin.get("/api/v1/resource-operations/" + response.json()["id"]).json()
    assert result["state"] == "failed"
    assert "不包含 dingo-cache" in result["message"]
    assert not runner


def test_tag_list_endpoint_uses_authenticated_metadata_query(admin, monkeypatch):
    seen = []
    monkeypatch.setattr(cache_images, "list_tags", lambda page, search: seen.append((page, search)) or {"items": [], "count": 0, "next_page": None})
    response = admin.get("/api/v1/cache-image-tags?page=2&search=v5.2")
    assert response.status_code == 200
    assert seen == [(2, "v5.2")]
