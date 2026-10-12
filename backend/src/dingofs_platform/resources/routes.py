from uuid import UUID
from fastapi import APIRouter, Request, Depends, BackgroundTasks
from pydantic import BaseModel, Field, ConfigDict, SecretStr
from dingofs_platform.auth.dependencies import current_user
from dingofs_platform.db import get_db
from dingofs_platform.inventory.service import lock_inventory
from . import service, execution
from .views import operation_view

router = APIRouter(prefix="/api/v1", tags=["cluster-resources"])


class OperationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(max_length=40)
    parameters: dict = Field(default_factory=dict)
    base_revision: int = Field(ge=1, strict=True)
    request_id: UUID
    confirmed: bool = Field(default=False, strict=True)


class AuthenticationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge: str = Field(min_length=32, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=4096)


@router.get("/clusters/{id}/resources")
def inventory(id: str, request: Request, user=Depends(current_user)):
    return service.inventory(request, id)


@router.post("/clusters/{id}/resource-operations", status_code=202)
def create(
    id: str,
    payload: OperationInput,
    request: Request,
    tasks: BackgroundTasks,
    user=Depends(current_user),
):
    op, new = service.create(request, id, payload)
    if new:
        tasks.add_task(execution.run, request, op["id"])
    return op


@router.get("/resource-operations/{id}")
def operation(id: str, request: Request, user=Depends(current_user)):
    with get_db(request) as db, db.begin():
        lock_inventory(db)
        return operation_view(db, execution.owned(db, request, id), private=True)


@router.post("/resource-operations/{id}/authenticate")
def authenticate(
    id: str,
    payload: AuthenticationInput,
    request: Request,
    tasks: BackgroundTasks,
    user=Depends(current_user),
):
    return execution.authenticate(
        request, id, payload.challenge, payload.password.get_secret_value(), tasks
    )


@router.post("/resource-operations/{id}/cancel")
def cancel(id: str, request: Request, user=Depends(current_user)):
    return execution.cancel(request, id)
