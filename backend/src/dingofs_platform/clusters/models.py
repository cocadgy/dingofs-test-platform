from datetime import datetime
from sqlalchemy import String, DateTime, JSON, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column
from dingofs_platform.db import Base, Record


class ClusterOperation(Record, Base):
    __tablename__ = "cluster_operations"
    actor_id: Mapped[str] = mapped_column(String(36))
    session_id: Mapped[str] = mapped_column(String(36))
    parameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    kind: Mapped[str] = mapped_column(String(16))
    machine_id: Mapped[str] = mapped_column(ForeignKey("machines.id"))
    machine_revision: Mapped[int] = mapped_column(Integer)
    target_user: Mapped[str] = mapped_column(String(80))
    cluster_id: Mapped[str | None] = mapped_column(ForeignKey("clusters.id"))
    cluster_revision: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(24), default="pending")
    lease_token: Mapped[str] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(80))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    challenge_digest: Mapped[str | None] = mapped_column(String(64))
    auth_account: Mapped[str | None] = mapped_column(String(80))
    auth_attempts: Mapped[int] = mapped_column(Integer, default=0)
