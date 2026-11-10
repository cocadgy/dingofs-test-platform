from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from dingofs_platform.db import Base, Record


class OperationLease(Record, Base):
    """One reentrant record per owner/key/mode, not an exclusive key lock.

    The lease service must serialize conflict checks before acquisition. Expiry
    alone does not prove a remote operation has ended or permit reclamation.
    """
    __tablename__ = 'operation_leases'
    key: Mapped[str] = mapped_column(String(512))
    owner: Mapped[str] = mapped_column(String(128))
    mode: Mapped[str] = mapped_column(String(16))
    depth: Mapped[int] = mapped_column(default=1)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint('key', 'owner', 'mode', name='uq_operation_lease_owner_mode'),
        CheckConstraint("mode IN ('shared','exclusive')", name='ck_operation_lease_mode'),
        CheckConstraint('depth >= 0', name='ck_operation_lease_depth'),
        Index('ix_operation_lease_key_released', 'key', 'released_at'),
    )
