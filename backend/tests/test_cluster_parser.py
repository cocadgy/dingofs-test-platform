from pathlib import Path
import pytest
from dingofs_platform.clusters.parser import (
    parse_cluster_names,
    parse_cluster_status,
    ClusterParseError,
)

RAW = (Path(__file__).parent / "fixtures/dingo/cluster-status-main.txt").read_text()


def test_sample():
    assert parse_cluster_names(" main-dingofs\n\ntest-dingofs\nmain-dingofs\n") == [
        "main-dingofs",
        "test-dingofs",
    ]
    r = parse_cluster_status(RAW, "main-dingofs")
    assert (
        r.node_count,
        r.service_count,
        r.running_instances,
        r.expected_instances,
    ) == (1, 10, 10, 10)
    assert r.role_counts == dict(coordinator=3, store=3, mds=3, executor=1)
    assert r.services[0].status_text == "Up 19 hours" and r.services[6].data_dir is None
    assert r.state == "running"


@pytest.mark.parametrize("bad", ["error: denied", "x" * 121, "x\x00", "a b"])
def test_bad_names(bad):
    with pytest.raises(ClusterParseError):
        parse_cluster_names(bad)


def test_variants():
    assert parse_cluster_names("") == []
    assert parse_cluster_names("\x1b[32mmain\x1b[0m\r\n") == ["main"]
    with pytest.raises(ClusterParseError):
        parse_cluster_status(RAW, "wrong")
    with pytest.raises(ClusterParseError):
        parse_cluster_status(
            RAW.replace("Get Service Status: [OK]", "Get Service Status: [FAIL]"),
            "main-dingofs",
        )
    with pytest.raises(ClusterParseError):
        parse_cluster_status(RAW + "broken row\n", "main-dingofs")
    assert (
        parse_cluster_status(
            RAW.replace("Up 19 hours", "Up 19 hours (unhealthy)"), "main-dingofs"
        ).state
        == "degraded"
    )
    assert (
        parse_cluster_status(
            RAW.replace("1/1", "0/1").replace("Up 19 hours", "Exited (0) 1 hour ago"),
            "main-dingofs",
        ).state
        == "stopped"
    )
    assert (
        parse_cluster_status(RAW.replace("1/1", "2/1"), "main-dingofs").state
        == "degraded"
    )
    assert (
        parse_cluster_status(RAW[: RAW.index("5dac8")], "main-dingofs").state
        == "unknown"
    )


def test_noninteractive_progress_output():
    raw = (Path(__file__).parent / "fixtures/dingo/cluster-status-noninteractive.txt").read_text()
    result = parse_cluster_status(raw, "main-dingofs")
    assert result.service_count == 10
    assert result.state == "running"
    assert result.running_instances == result.expected_instances == 10


def test_progress_does_not_hide_invalid_headers_or_rows():
    for raw in ["…\nunknown header\n" + RAW, RAW + "…\n"]:
        with pytest.raises(ClusterParseError):
            parse_cluster_status(raw, "main-dingofs")


def test_coordinator_backend_status_header():
    import re
    raw = re.sub(r"tikv\s+addr\s*:.*", "coordinator addr : 10.220.32.40:6540,10.220.32.41:6540,10.220.32.42:6540", RAW)
    raw = raw.replace("main-dingofs", "mdsv2-cluster").replace("Get Service Status: [OK]", "…\n\x1b[1A\x1b[J…")
    result = parse_cluster_status(raw, "mdsv2-cluster")
    assert result.cluster_name == "mdsv2-cluster"
    assert result.service_count == result.running_instances == 10
    assert result.state == "running"
    assert result.tikv_addresses == []
    with pytest.raises(ClusterParseError, match="target_mismatch"):
        parse_cluster_status(raw, "another-cluster")
    with pytest.raises(ClusterParseError, match="invalid_header"):
        parse_cluster_status(raw.replace("coordinator addr :", "coordinator addr : duplicate\ncoordinator addr :"), "mdsv2-cluster")
