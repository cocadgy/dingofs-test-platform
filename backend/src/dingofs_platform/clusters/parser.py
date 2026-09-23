"""Pure bounded parsers for the user-supplied dingo CLI format."""

import re
from collections import Counter
from .schemas import ClusterSnapshot, ServiceRow

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,119}\Z")


class ClusterParseError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def clean(raw):
    if len(raw.encode()) > 2097152:
        raise ClusterParseError("output_limit")
    value = ANSI.sub("", raw).replace("\r\n", "\n")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ClusterParseError("invalid_control")
    return value


def parse_cluster_names(raw):
    names = []
    for line in clean(raw).splitlines():
        name = line.strip()
        if not name:
            continue
        if not NAME.fullmatch(name):
            raise ClusterParseError("invalid_listing")
        if name not in names:
            names.append(name)
        if len(names) > 1000:
            raise ClusterParseError("invalid_listing")
    return names


ROW = re.compile(
    r"^(\S+)\s+(\S+)\s+(\S+)\s+(\d+)/(\d+)\s+(\S+)\s+(.+?)\s+(\d+(?:,\d+)*|-)\s+(/\S*|-)\s+(/\S*|-)\s+(/\S*|-)\s*$"
)


def parse_cluster_status(raw, expected_name):
    heads = {}
    services = []
    table = False
    for raw_line in clean(raw).splitlines():
        line = raw_line.strip()
        if not line or re.fullmatch(r"[-=\s]+", line):
            continue
        # Non-interactive dingo emits progress ellipses with ANSI cursor erases.
        # Only accept this known preamble before any metadata or service rows.
        if not heads and not table and line == "…":
            continue
        if line.startswith("Get Service Status:"):
            if line != "Get Service Status: [OK]":
                raise ClusterParseError("query_failed")
            continue
        if re.match(
            r"^Id\s+Role\s+Host\s+Instances\s+Container Id\s+Status\s+Ports\s+Log Dir\s+Data Dir\s+Raft Dir$",
            line,
        ):
            table = True
            continue
        if not table:
            match = re.match(
                r"^(cluster\s+name|cluster\s+kind|mds\s+addr|tikv\s+addr)\s*:\s*(.*)$",
                line,
            )
            if not match:
                raise ClusterParseError("invalid_header")
            key = " ".join(match[1].split())
            if key in heads:
                raise ClusterParseError("invalid_header")
            heads[key] = match[2].strip()
            continue
        m = ROW.fullmatch(line)
        if not m:
            raise ClusterParseError("invalid_row")
        (
            sid,
            role,
            host,
            running,
            expected,
            container,
            status,
            ports,
            log,
            data,
            raft,
        ) = m.groups()
        running, expected = int(running), int(expected)
        low = status.lower()
        if (
            low.startswith("up")
            and "unhealthy" not in low
            and "(health: starting)" not in low
        ):
            state = "running" if running == expected and expected > 0 else "degraded"
        elif low.startswith(("exited", "stopped", "created", "down")) and running == 0:
            state = "stopped"
        elif low.startswith(("up", "restarting", "dead", "paused")):
            state = "degraded"
        else:
            state = "unknown"
        services.append(
            ServiceRow(
                id=sid,
                role=role,
                host=host,
                running_instances=running,
                expected_instances=expected,
                container_id=None if container == "-" else container,
                status_text=status,
                state=state,
                ports=[] if ports == "-" else ports.split(","),
                log_dir=None if log == "-" else log,
                data_dir=None if data == "-" else data,
                raft_dir=None if raft == "-" else raft,
            )
        )
    if not table or not heads.get("cluster kind") or not heads.get("cluster name"):
        raise ClusterParseError("invalid_header")
    if heads["cluster name"] != expected_name:
        raise ClusterParseError("target_mismatch")
    if len({s.id for s in services}) != len(services):
        raise ClusterParseError("invalid_row")
    states = {s.state for s in services}
    state = "unknown"
    if states == {"running"}:
        state = "running"
    elif states == {"stopped"}:
        state = "stopped"
    elif "degraded" in states or ("stopped" in states and "running" in states):
        state = "degraded"
    return ClusterSnapshot(
        cluster_name=expected_name,
        cluster_kind=heads["cluster kind"],
        mds_addresses=[
            a.strip()
            for a in heads.get("mds addr", "").split(",")
            if a.strip() and a.strip() != "-"
        ],
        tikv_addresses=[
            a.strip()
            for a in heads.get("tikv addr", "").split(",")
            if a.strip() and a.strip() != "-"
        ],
        services=services,
        role_counts=dict(Counter(s.role for s in services)),
        node_count=len({s.host for s in services}),
        service_count=len(services),
        running_instances=sum(s.running_instances for s in services),
        expected_instances=sum(s.expected_instances for s in services),
        state=state,
    )
