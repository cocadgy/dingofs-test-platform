import pytest
from dingofs_platform.inventory.routes import validated
from dingofs_platform.errors import Problem


def test_chinese_display_name_does_not_change_ssh_identity():
    data = validated(
        "machines",
        {
            "name": "中文测试机器（北京）01",
            "address": "192.0.2.10",
            "ssh_user": "jenkins",
        },
    )
    assert data["name"] == "中文测试机器（北京）01"
    assert data["address"] == "192.0.2.10"
    assert data["ssh_user"] == "jenkins"


def test_validation_identifies_other_field_without_exposing_input():
    with pytest.raises(Problem) as caught:
        validated(
            "machines",
            {
                "name": "中文测试机器",
                "address": "invalid host",
                "ssh_user": "用户名",
                "ssh_password": "must-not-appear",
            },
        )
    error = caught.value
    assert "主机地址" in error.message and "SSH 用户" in error.message
    assert set(error.details["fields"]) == {"address", "ssh_user"}
    assert "must-not-appear" not in str(error.details) + error.message


def test_create_rename_search_chinese_machine(admin):
    response = admin.post(
        "/api/v1/machines",
        json={"name": "北京测试机器01", "address": "192.0.2.10", "ssh_user": "jenkins"},
    )
    assert response.status_code == 201, response.text
    machine = response.json()
    response = admin.patch(
        "/api/v1/machines/" + machine["id"],
        json={"base_revision": machine["revision"], "name": "上海测试机器02"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "上海测试机器02"
    result = admin.get("/api/v1/machines", params={"q": "上海测试"}).json()
    assert [row["id"] for row in result["items"]] == [machine["id"]]
    assert result["items"][0]["address"] == "192.0.2.10"
