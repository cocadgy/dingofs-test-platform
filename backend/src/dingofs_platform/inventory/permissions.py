"""Immutable creator ownership; legacy and deleted-user resources remain admin-managed."""

from dingofs_platform.errors import Problem


def can_manage(actor, resource):
    return bool(
        actor
        and not actor.disabled
        and (
            actor.role == "admin"
            or (
                getattr(resource, "creator_id", None) is not None
                and resource.creator_id == actor.id
            )
        )
    )


def require_manage(actor, resource):
    if not can_manage(actor, resource):
        raise Problem(403, "forbidden", "只能操作自己创建的资源，管理员可管理全部资源")
