from fastapi import APIRouter, Depends, Query, Request

from dingofs_platform.auth.dependencies import current_user
from dingofs_platform.auth.users import actor_in_transaction
from dingofs_platform.db import get_db
from dingofs_platform.errors import Problem
from dingofs_platform.inventory.permissions import require_manage
from dingofs_platform.inventory.service import audit, lock_inventory
from . import service
from .models import StorageProfile
from .schemas import StorageProfileInput, StorageProfileUpdate, StorageProfileView


router = APIRouter(prefix="/api/v1/storage-profiles", tags=["storage-profiles"])


@router.get("", response_model=list[StorageProfileView])
def listing(request: Request, user=Depends(current_user)):
    with get_db(request) as db, db.begin():
        actor = actor_in_transaction(db, request)
        return service.listing(db, actor)


@router.post("", response_model=StorageProfileView, status_code=201)
def create(payload: StorageProfileInput, request: Request, user=Depends(current_user)):
    with get_db(request) as db, db.begin():
        actor = actor_in_transaction(db, request)
        lock_inventory(db)
        public, ciphertext = service.credential_data(
            payload.storage_type, payload.parameters,
            request.app.state.settings.credential_encryption_key,
        )
        row = StorageProfile(
            creator_id=actor.id, name=payload.name, storage_type=payload.storage_type,
            description=payload.description, enabled=payload.enabled,
            parameters=public, secret_ciphertext=ciphertext,
        )
        db.add(row)
        db.flush()
        audit(db, actor, "storage_profile.create", "storage-profiles/" + row.id, payload.model_fields_set)
        return service.view(row, actor)


@router.put("/{id}", response_model=StorageProfileView)
def update(id: str, payload: StorageProfileUpdate, request: Request, user=Depends(current_user)):
    with get_db(request) as db, db.begin():
        actor = actor_in_transaction(db, request)
        lock_inventory(db)
        row = service.active(db, id)
        require_manage(actor, row)
        service.check_revision(row, payload.revision)
        if row.storage_type != payload.storage_type:
            raise Problem(422, "storage_type_immutable", "存储类型不能修改，请新建存储配置")
        public, ciphertext = service.credential_data(
            payload.storage_type, payload.parameters,
            request.app.state.settings.credential_encryption_key, previous=row,
        )
        row.name, row.description, row.enabled = payload.name, payload.description, payload.enabled
        row.parameters, row.secret_ciphertext = public, ciphertext
        row.revision += 1
        db.flush()
        audit(db, actor, "storage_profile.update", "storage-profiles/" + row.id, payload.model_fields_set - {"revision"})
        return service.view(row, actor)


@router.delete("/{id}", status_code=204)
def delete(id: str, request: Request, revision: int = Query(ge=1), user=Depends(current_user)):
    with get_db(request) as db, db.begin():
        actor = actor_in_transaction(db, request)
        lock_inventory(db)
        row = service.active(db, id)
        require_manage(actor, row)
        service.check_revision(row, revision)
        row.deleted = True
        row.enabled = False
        row.secret_ciphertext = ""
        row.revision += 1
        audit(db, actor, "storage_profile.delete", "storage-profiles/" + row.id, [])
