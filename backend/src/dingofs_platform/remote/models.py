"""Remote access metadata only: command input and log/terminal text stay in RAM."""

from datetime import datetime
from sqlalchemy import String, JSON, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from dingofs_platform.db import Base, Record


class RemoteSession(Record, Base):
    __tablename__ = "remote_sessions"
    actor_id: Mapped[str] = mapped_column(String(36), index=True)
    login_session_id: Mapped[str] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(24))
    cluster_id: Mapped[str | None] = mapped_column(ForeignKey("clusters.id"))
    machine_id: Mapped[str] = mapped_column(ForeignKey("machines.id"), index=True)
    cluster_revision: Mapped[int | None]
    machine_revision: Mapped[int]
    target_user: Mapped[str] = mapped_column(String(80))
    service_id: Mapped[str | None] = mapped_column(String(160))
    log_root: Mapped[str | None] = mapped_column(String(4096))
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(24), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    auth_account: Mapped[str | None] = mapped_column(String(80))
    auth_attempts: Mapped[int] = mapped_column(default=0)
    challenge_hash: Mapped[str | None] = mapped_column(String(64))
    auth_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    result: Mapped[dict | None] = mapped_column(JSON)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
