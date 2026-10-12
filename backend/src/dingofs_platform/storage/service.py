"""Write-only profile secrets and atomic snapshots for filesystem creation."""

import json

from sqlalchemy import select

from dingofs_platform.errors import Problem
from dingofs_platform.inventory.credentials import decrypt_password, encrypt_password
from dingofs_platform.inventory.permissions import can_manage
from .models import StorageProfile
from .schemas import SECRET_FIELDS, STORAGE_FIELDS


def view(row, actor):
    return dict(
        id=row.id, name=row.name, storage_type=row.storage_type,
        description=row.description, enabled=row.enabled, revision=row.revision,
        creator_id=row.creator_id, can_manage=can_manage(actor, row),
        parameters=dict(row.parameters), has_secrets=bool(row.secret_ciphertext),
        created_at=row.created_at, updated_at=row.updated_at,
    )


def listing(db, actor):
    return [
        view(row, actor)
        for row in db.scalars(
            select(StorageProfile).where(StorageProfile.deleted == False)
            .order_by(StorageProfile.name, StorageProfile.id)
        )
    ]


def active(db, profile_id):
    row = db.get(StorageProfile, profile_id)
    if not row or row.deleted:
        raise Problem(404, "not_found", "存储配置不存在或已删除")
    return row


def check_revision(row, revision):
    if row.revision != revision:
        raise Problem(409, "revision_conflict", "存储配置已更新，请刷新后重试")


def _decrypt(row, key):
    try:
        secret = json.loads(decrypt_password(row.secret_ciphertext, key))
        if not isinstance(secret, dict):
            raise ValueError("invalid credential object")
        return secret
    except (Problem, TypeError, ValueError):
        raise Problem(503, "storage_credentials_unavailable", "无法读取存储凭据，请检查平台加密密钥或重新配置凭据") from None


def credential_data(storage_type, parameters, key, *, previous=None):
    allowed = set(STORAGE_FIELDS[storage_type])
    if parameters.keys() - allowed:
        raise Problem(422, "invalid_parameters", "存储参数与所选存储类型不匹配")
    preserve = SECRET_FIELDS.intersection(allowed) - {
        field for field, value in parameters.items() if value
    }
    saved = _decrypt(previous, key) if previous and preserve else {}
    public, secret = {}, {}
    for field in STORAGE_FIELDS[storage_type]:
        value = parameters.get(field, "")
        if field in SECRET_FIELDS and not value:
            value = saved.get(field, "")
        if (
            not isinstance(value, str) or not value.strip() or len(value) > 4096
            or any(ord(char) < 32 for char in value)
        ):
            raise Problem(422, "invalid_parameters", "请检查存储连接参数和必填凭据")
        if field in SECRET_FIELDS:
            secret[field] = value
        else:
            public[field] = value.strip()
    return public, encrypt_password(json.dumps(secret), key)


def resolve(db, profile_id, revision, key):
    """Caller holds inventory lock; pending work owns this immutable snapshot."""
    row = db.get(StorageProfile, profile_id)
    if not row or row.deleted or not row.enabled:
        raise Problem(422, "storage_profile_unavailable", "存储配置不存在、已停用或已删除，请重新选择")
    check_revision(row, revision)
    secret = _decrypt(row, key)
    expected = SECRET_FIELDS.intersection(STORAGE_FIELDS[row.storage_type])
    if set(secret) != expected or not all(isinstance(value, str) and value for value in secret.values()):
        raise Problem(503, "storage_credentials_unavailable", "存储凭据不可用，请重新配置")
    return (
        dict(row.parameters, **secret, storage_type=row.storage_type),
        dict(storage_profile_id=row.id, storage_profile_revision=row.revision, source_name=row.name),
    )
