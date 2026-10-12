"""Managed remote resources and resumable, authenticated resource operations."""

from datetime import datetime
from sqlalchemy import (
    String,
    Text,
    JSON,
    DateTime,
    Integer,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from dingofs_platform.db import Base, Record


class ManagedResource(Record, Base):
    __tablename__ = "managed_resources"
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id"), index=True)
    creator_id: Mapped[str] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(4096))
    state: Mapped[str] = mapped_column(String(24), default="pending")
    data: Mapped[dict] = mapped_column(JSON)


class ResourceOperation(Record, Base):
    __tablename__ = "resource_operations"
    __table_args__ = (
        UniqueConstraint(
            "actor_id", "cluster_id", "request_id", name="uq_resource_request"
        ),
    )
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id"), index=True)
    cluster_revision: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[str] = mapped_column(String(36))
    session_id: Mapped[str] = mapped_column(String(36))
    request_id: Mapped[str] = mapped_column(String(36))
    request_digest: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(24), default="pending")
    parameters: Mapped[dict] = mapped_column(JSON)
    secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps: Mapped[list] = mapped_column(JSON)
    cursor: Mapped[int] = mapped_column(Integer, default=0)
    resource_id: Mapped[str | None] = mapped_column(
        ForeignKey("managed_resources.id"), nullable=True
    )
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lease_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    auth_account: Mapped[str | None] = mapped_column(String(80), nullable=True)
    challenge_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    auth_attempts: Mapped[int] = mapped_column(Integer, default=0)
