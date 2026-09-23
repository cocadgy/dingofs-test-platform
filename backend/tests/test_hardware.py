import json
import pytest
from dingofs_platform.inventory.ssh_transport import CommandResult
from dingofs_platform.inventory.hardware import parse_hardware, collect


def result(value):
    return CommandResult(value if isinstance(value, str) else json.dumps(value), "", 0)


@pytest.fixture
def sample():
    return {
        "cpu": result(
            {
                "lscpu": [
                    {"field": "Model name:", "data": "CPU Model"},
                    {"field": "CPU(s):", "data": "8"},
                    {"field": "Socket(s):", "data": "2"},
                    {"field": "Core(s) per socket:", "data": "2"},
                ]
            }
        ),
        "memory": result("MemTotal:       1024 kB\nMemFree: 100 kB\n"),
        "disks": result(
            {
                "blockdevices": [
                    {
                        "name": "sda",
                        "type": "disk",
                        "size": 1000,
                        "model": "disk",
                        "rota": True,
                        "children": [
                            {
                                "name": "sda1",
                                "type": "part",
                                "size": 600,
                                "children": [
                                    {"name": "vg-x", "type": "lvm", "size": 600}
                                ],
                            }
                        ],
                    }
                ]
            }
        ),
        "filesystems": result(
            "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/sda1 100 20 80 20% /mnt/a space\n/dev/sda1 100 20 80 20% /mnt/b\n"
        ),
        "mounts": result(
            "1 0 8:1 / /mnt/a\\040space rw - ext4 /dev/sda1 rw\n2 0 8:1 / /mnt/b rw - ext4 /dev/sda1 rw\n"
        ),
        "interfaces": result(
            [
                {
                    "ifname": "eth0",
                    "address": "00:11:22:33:44:55",
                    "operstate": "UP",
                    "mtu": 1500,
                    "addr_info": [
                        {"family": "inet", "local": "10.0.0.1", "prefixlen": 24},
                        {"family": "inet6", "local": "2001:db8::1", "prefixlen": 64},
                    ],
                }
            ]
        ),
        "speeds": result("eth0\t10000\n"),
        "rdma": result("mlx5_0\t1\teth0\n"),
    }


def test_realistic_snapshot(sample):
    data = parse_hardware(sample)
    assert data["cpu"]["physical_cores"] == 4 and data["cpu"]["logical_cores"] == 8
    assert data["memory"]["total_bytes"] == 1048576
    assert sum(d["size_bytes"] for d in data["disks"] if d["type"] == "disk") == 1000
    assert len(data["disks"]) == 3
    assert data["filesystems"][0]["mountpoint"] == "/mnt/a space"
    assert data["filesystems"][1]["same_filesystem_as"] == "/mnt/a space"
    assert data["interfaces"][0]["speed_mbps"] == 10000
    assert "2001:db8::1/64" in data["interfaces"][0]["addresses"]
    assert data["rdma"][0]["device"] == "mlx5_0"
    assert data["warnings"] == []


def test_missing_optional_information_is_unknown(sample):
    sample["cpu"] = result(
        {
            "lscpu": [
                {"field": "CPU(s):", "data": "8"},
                {"field": "Hypervisor vendor:", "data": "KVM"},
            ]
        }
    )
    sample["speeds"] = result("eth0\t-1\n")
    sample["rdma"] = result("")
    data = parse_hardware(sample)
    assert data["cpu"]["physical_cores"] is None
    assert data["interfaces"][0]["speed_mbps"] is None
    assert data["rdma"] == []
    assert data["warnings"]


@pytest.mark.parametrize(
    "bad", [None, [], {"lscpu": "invalid"}, "{broken", {"lscpu": [{}]}]
)
def test_malformed_cpu_does_not_discard_other_fields(sample, bad):
    sample["cpu"] = result(bad)
    data = parse_hardware(sample)
    assert data["cpu"] is None
    assert data["memory"]["total_bytes"] == 1048576
    assert data["warnings"]


def test_collection_status(sample):
    ok = collect(None, transport=lambda *a, **k: sample)
    assert ok["status"] == "success"
    sample["memory"] = CommandResult("", "missing tool", 127)
    assert collect(None, transport=lambda *a, **k: sample)["status"] == "partial"
    assert collect(None, transport=lambda *a, **k: {})["status"] == "failed"


def test_untrusted_numbers_and_large_document(sample):
    sample["memory"] = result("MemTotal: -1 kB")
    sample["disks"] = result(" " * 1048577)
    sample["interfaces"] = result({"not": "a list"})
    data = parse_hardware(sample)
    assert (
        data["memory"] is None and data["disks"] is None and data["interfaces"] is None
    )
