from sqlalchemy import select
from dingofs_platform.errors import Problem
from dingofs_platform.inventory.permissions import can_manage
from .models import CacheProfile
from .catalog import CATALOG, SOURCE_VERSION, validate_options

def catalog():
    return dict(source_version=SOURCE_VERSION, fields=CATALOG)

def view(row, actor):
    return dict(id=row.id, name=row.name, description=row.description, enabled=row.enabled, revision=row.revision, creator_id=row.creator_id, can_manage=can_manage(actor, row), parameters=dict(row.parameters), source_version=row.source_version, created_at=row.created_at, updated_at=row.updated_at)

def listing(db, actor):
    return [view(row, actor) for row in db.scalars(select(CacheProfile).where(CacheProfile.deleted == False).order_by(CacheProfile.name, CacheProfile.id))]

def active(db, id):
    row = db.get(CacheProfile, id)
    if not row or row.deleted:
        raise Problem(404, 'not_found', '缓存组配置不存在或已删除')
    return row

def revision(row, value):
    if row.revision != value:
        raise Problem(409, 'revision_conflict', '缓存组配置已更新，请刷新后重新选择')

def unique_name(db, name, id=None):
    row = db.scalar(select(CacheProfile).where(CacheProfile.name == name, CacheProfile.deleted == False))
    if row and row.id != id:
        raise Problem(409, 'name_conflict', '缓存组配置名称已存在')

def resolve(db, id, rev):
    row = active(db, id)
    revision(row, rev)
    if not row.enabled:
        raise Problem(422, 'cache_profile_disabled', '缓存组配置已停用，请重新选择')
    return (validate_options(row.parameters), dict(cache_profile_id=row.id, cache_profile_revision=row.revision, cache_profile_name=row.name, cache_profile_source_version=row.source_version))
