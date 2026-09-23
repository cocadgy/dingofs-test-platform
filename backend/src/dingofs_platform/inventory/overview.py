"""Compact machine rows for the overview; never serialize credentials or raw snapshots."""

from datetime import datetime, timezone
import ipaddress
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select, func
from dingofs_platform.auth.dependencies import current_user
from dingofs_platform.db import get_db
from .models import Machine

router = APIRouter(prefix="/api/v1/machines", tags=["machine-overview"])


class MachineOverviewItem(BaseModel):
    id: str
    name: str
    address: str
    ip: str
    archived: bool
    collection_status: str
    hardware_source: str
    cpu_model: str | None
    physical_cores: int | None
    logical_cores: int | None
    memory_bytes: int | None
    disk_bytes: int | None
    max_speed_mbps: int | None
    rdma_devices: list[str] | None
    info_updated_at: datetime | None


class MachineOverviewList(BaseModel):
    items: list[MachineOverviewItem]
    total: int


def valid_number(value):
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None
    )


def overview(row):
    info = row["hardware_info"]
    source = "complete"
    updated = row["last_success_at"]
    if not info:
        info = (
            row["last_attempt_info"] if row["collection_status"] == "partial" else None
        )
        source = "partial" if info else "none"
        updated = row["last_attempt_at"] if info else None
    info = info or {}
    cpu = info.get("cpu") or {}
    memory = info.get("memory") or {}
    disks = info.get("disks")
    physical = {
        d["name"]: valid_number(d.get("size_bytes"))
        for d in disks or []
        if d.get("type") == "disk"
    }
    capacity = (
        sum(physical.values())
        if physical and all(v is not None for v in physical.values())
        else None
    )
    interfaces = info.get("interfaces") or []
    speeds = [
        valid_number(n.get("speed_mbps")) for n in interfaces if n.get("name") != "lo"
    ]
    speeds = [n for n in speeds if n is not None and n > 0]
    try:
        ip = str(ipaddress.ip_address(row["address"]))
    except ValueError:
        addresses = set()
        for nic in interfaces:
            for value in nic.get("addresses", []):
                try:
                    parsed = ipaddress.ip_interface(value).ip
                except ValueError:
                    continue
                if not (
                    parsed.is_loopback
                    or parsed.is_link_local
                    or parsed.is_multicast
                    or parsed.is_unspecified
                ):
                    addresses.add(parsed)
        ip = (
            ", ".join(
                str(a) for a in sorted(addresses, key=lambda a: (a.version, int(a)))
            )
            or row["address"]
        )
    rdma = info.get("rdma")
    status = row["collection_status"]
    if (
        status == "collecting"
        and row["collection_expires_at"]
        and row["collection_expires_at"] <= datetime.now(timezone.utc)
    ):
        status = "interrupted"
    return {
        "id": row["id"],
        "name": row["name"],
        "address": row["address"],
        "ip": ip,
        "archived": row["archived"],
        "collection_status": status,
        "hardware_source": source,
        "cpu_model": cpu.get("model"),
        "physical_cores": valid_number(cpu.get("physical_cores")),
        "logical_cores": valid_number(cpu.get("logical_cores")),
        "memory_bytes": valid_number(memory.get("total_bytes")),
        "disk_bytes": capacity,
        "max_speed_mbps": max(speeds, default=None),
        "rdma_devices": sorted({r["device"] for r in rdma if r.get("device")})
        if rdma is not None
        else None,
        "info_updated_at": updated,
    }


@router.get("/overview", response_model=MachineOverviewList)
def listing(
    request: Request,
    limit: int = Query(200, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user=Depends(current_user),
):
    columns = (
        "id",
        "name",
        "address",
        "archived",
        "collection_status",
        "hardware_info",
        "last_attempt_info",
        "last_success_at",
        "last_attempt_at",
        "collection_expires_at",
    )
    with get_db(request) as db:
        rows = db.execute(
            select(*(getattr(Machine, n) for n in columns))
            .order_by(Machine.created_at, Machine.id)
            .offset(offset)
            .limit(limit)
        ).mappings()
        return {
            "items": [overview(row) for row in rows],
            "total": db.scalar(select(func.count()).select_from(Machine)),
        }
