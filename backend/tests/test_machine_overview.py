from datetime import datetime, timezone
from dingofs_platform.inventory.models import Machine
from conftest import machine


def snapshot():
    return {
        "cpu": {"model": "Example CPU", "physical_cores": 4, "logical_cores": 8},
        "memory": {"total_bytes": 64 * 1024**3},
        "disks": [
            {"name": "sda", "type": "disk", "size_bytes": 1024**4},
            {"name": "sda1", "type": "part", "size_bytes": 1024**4},
        ],
        "interfaces": [
            {"name": "lo", "speed_mbps": None, "addresses": ["127.0.0.1/8"]},
            {"name": "eth0", "speed_mbps": 10000, "addresses": ["10.0.0.2/24"]},
            {"name": "eth1", "speed_mbps": 100000, "addresses": ["10.0.0.3/24"]},
        ],
        "rdma": [{"device": "mlx5_0", "port": 1}, {"device": "mlx5_0", "port": 2}],
    }


def test_overview_projects_capacity_speed_ip_and_data_timestamp(admin, app):
    m = machine(admin)
    with app.state.session_factory.begin() as db:
        row = db.get(Machine, m["id"])
        row.hardware_info = snapshot()
        row.last_success_at = datetime(2026, 9, 20, 1, tzinfo=timezone.utc)
        row.last_attempt_at = datetime(2026, 9, 23, 1, tzinfo=timezone.utc)
        row.collection_status = "failed"
    r = admin.get("/api/v1/machines/overview")
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["cpu_model"] == "Example CPU"
    assert item["physical_cores"] == 4 and item["logical_cores"] == 8
    assert item["memory_bytes"] == 64 * 1024**3
    assert item["disk_bytes"] == 1024**4
    assert item["max_speed_mbps"] == 100000
    assert item["rdma_devices"] == ["mlx5_0"]
    assert item["ip"] == "10.0.0.2, 10.0.0.3"
    assert item["info_updated_at"].startswith("2026-09-20")
    assert item["hardware_source"] == "complete"
    assert "hardware_info" not in item and "ssh_password_ciphertext" not in item


def test_missing_information_is_not_zero_and_registered_ip_wins(admin, app):
    m = machine(admin)
    with app.state.session_factory.begin() as db:
        db.get(Machine, m["id"]).address = "10.0.0.20"
    item = admin.get("/api/v1/machines/overview").json()["items"][0]
    assert item["ip"] == "10.0.0.20"
    for field in [
        "cpu_model",
        "physical_cores",
        "logical_cores",
        "memory_bytes",
        "disk_bytes",
        "max_speed_mbps",
        "rdma_devices",
        "info_updated_at",
    ]:
        assert item[field] is None


def test_partial_results_use_matching_attempt_time(admin, app):
    m = machine(admin)
    with app.state.session_factory.begin() as db:
        row = db.get(Machine, m["id"])
        row.last_attempt_info = snapshot()
        row.collection_status = "partial"
        row.last_attempt_at = datetime(2026, 9, 23, 1, tzinfo=timezone.utc)
    item = admin.get("/api/v1/machines/overview").json()["items"][0]
    assert item["hardware_source"] == "partial"
    assert item["info_updated_at"].startswith("2026-09-23")


def test_overview_pagination_and_authorization(client, admin, app):
    for n in range(3):
        machine(admin, "node" + str(n))
    first = admin.get("/api/v1/machines/overview?limit=2").json()
    second = admin.get("/api/v1/machines/overview?limit=2&offset=2").json()
    assert first["total"] == second["total"] == 3
    assert len(first["items"]) == 2 and len(second["items"]) == 1
    assert not set(x["id"] for x in first["items"]) & set(
        x["id"] for x in second["items"]
    )
    r = client.post(
        "/api/v1/auth/login",
        json={"username": "member", "password": "test-password-123"},
    )
    assert r.status_code == 200
    assert client.get("/api/v1/machines/overview").status_code == 200
    client.cookies.clear()
    assert client.get("/api/v1/machines/overview").status_code == 401


def test_overview_marks_an_expired_collection_as_interrupted(admin, app):
    m = machine(admin)
    with app.state.session_factory.begin() as db:
        row = db.get(Machine, m["id"])
        row.collection_status = "collecting"
        row.collection_expires_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
    item = admin.get("/api/v1/machines/overview").json()["items"][0]
    assert item["collection_status"] == "interrupted"
