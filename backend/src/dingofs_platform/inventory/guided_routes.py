from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import Field, StringConstraints, field_validator

from dingofs_platform.auth.dependencies import current_user
from dingofs_platform.auth.users import actor_in_transaction
from dingofs_platform.db import get_db
from dingofs_platform.errors import Problem

from .credentials import credential_changes
from .hardware import collect
from .host_identity import normalize_host, sync_host_identifiers
from .models import Machine
from .schemas import MachineInput, Strict
from .service import audit, lock_inventory, serialize
from .ssh_transport import CollectionError, ERRORS, SSHConfig, execute


router = APIRouter(prefix="/api/v1/guided", tags=["guided-start"])


class GuidedMachineInput(Strict):
    name: str = Field(min_length=1, max_length=120)
    address: str = Field(min_length=1, max_length=255)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_user: str = Field(
        min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$"
    )
    ssh_password: Annotated[
        str, StringConstraints(strip_whitespace=False, min_length=1, max_length=4096)
    ]

    @field_validator("address")
    @classmethod
    def address_valid(cls, value):
        return normalize_host(value)


@router.post("/machines", status_code=201)
def create_guided_machine(
    payload: GuidedMachineInput,
    request: Request,
    user=Depends(current_user),
):
    settings = request.app.state.settings
    config = SSHConfig(
        payload.address,
        payload.ssh_port,
        payload.ssh_user,
        payload.ssh_password,
        settings.ssh_known_hosts,
    )
    try:
        result = collect(
            config,
            transport=getattr(request.app.state, "hardware_transport", execute),
            timeout_s=settings.collection_timeout_seconds,
        )
    except CollectionError as exc:
        raise Problem(422, exc.code, ERRORS[exc.code]) from None
    except Exception:
        raise Problem(
            422,
            "hardware_collection_failed",
            "机器信息采集失败，请检查机器配置后重试",
        ) from None
    if result["status"] == "failed":
        raise Problem(
            422,
            "hardware_collection_failed",
            "未能采集有效硬件信息，请检查远端工具和权限",
        )
    now = datetime.now(timezone.utc)
    machine_data = MachineInput.model_validate(
        {
            "name": payload.name,
            "address": payload.address,
            "ssh_port": payload.ssh_port,
            "ssh_user": payload.ssh_user,
            "ssh_password": payload.ssh_password,
        }
    ).model_dump()
    machine_data = credential_changes(
        machine_data, settings.credential_encryption_key
    )
    with get_db(request) as db, db.begin():
        actor = actor_in_transaction(db, request)
        lock_inventory(db)
        row = Machine(
            **machine_data,
            creator_id=actor.id,
            hardware_info=result["hardware_info"],
            last_attempt_info=result["hardware_info"],
            last_attempt_at=now,
            last_success_at=now if result["status"] == "success" else None,
            collection_status=result["status"],
            collection_error=None,
        )
        db.add(row)
        db.flush()
        sync_host_identifiers(db, row)
        audit(
            db,
            actor,
            "create",
            "machines/" + row.id,
            ["address", "name", "ssh_port", "ssh_user"],
        )
        db.flush()
        return serialize(db, "machines", row)
