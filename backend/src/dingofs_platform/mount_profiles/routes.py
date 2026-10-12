from fastapi import APIRouter, Depends, Query, Request
from dingofs_platform.auth.dependencies import current_user
from dingofs_platform.auth.users import actor_in_transaction
from dingofs_platform.db import get_db
from dingofs_platform.inventory.permissions import require_manage
from dingofs_platform.inventory.service import audit, lock_inventory
from . import service
from .catalog import SOURCE_VERSION
from .models import MountProfile
from .schemas import ProfileInput, ProfileUpdate, ProfileView
router = APIRouter(prefix='/api/v1/mount-profiles', tags=['mount-profiles'])

@router.get('/catalog')
def catalog(user=Depends(current_user)):
    return service.catalog()

@router.get('', response_model=list[ProfileView])
def listing(request: Request, user=Depends(current_user)):
    with get_db(request) as db, db.begin():
        return service.listing(db, actor_in_transaction(db, request))

@router.post('', response_model=ProfileView, status_code=201)
def create(payload: ProfileInput, request: Request, user=Depends(current_user)):
    with get_db(request) as db, db.begin():
        actor = actor_in_transaction(db, request)
        lock_inventory(db)
        service.unique_name(db, payload.name)
        row = MountProfile(creator_id=actor.id, source_version=SOURCE_VERSION, **payload.model_dump())
        db.add(row)
        db.flush()
        audit(db, actor, 'mount_profile.create', 'mount-profiles/' + row.id, payload.model_fields_set)
        return service.view(row, actor)

@router.put('/{id}', response_model=ProfileView)
def update(id: str, payload: ProfileUpdate, request: Request, user=Depends(current_user)):
    with get_db(request) as db, db.begin():
        actor = actor_in_transaction(db, request)
        lock_inventory(db)
        row = service.active(db, id)
        require_manage(actor, row)
        service.revision(row, payload.revision)
        service.unique_name(db, payload.name, id)
        for key, value in payload.model_dump(exclude={'revision'}).items():
            setattr(row, key, value)
        row.revision += 1
        row.source_version = SOURCE_VERSION
        db.flush()
        audit(db, actor, 'mount_profile.update', 'mount-profiles/' + id, payload.model_fields_set - {'revision'})
        return service.view(row, actor)

@router.delete('/{id}', status_code=204)
def delete(id: str, request: Request, revision: int=Query(ge=1), user=Depends(current_user)):
    with get_db(request) as db, db.begin():
        actor = actor_in_transaction(db, request)
        lock_inventory(db)
        row = service.active(db, id)
        require_manage(actor, row)
        service.revision(row, revision)
        row.deleted = True
        row.enabled = False
        row.revision += 1
        audit(db, actor, 'mount_profile.delete', 'mount-profiles/' + id, [])
