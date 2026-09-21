from sqlalchemy import String, JSON
from sqlalchemy.orm import Mapped, mapped_column
from dingofs_platform.db import Base, Record


class AuditEvent(Record, Base):
    __tablename__ = "audit_events"
    outcome: Mapped[str] = mapped_column(
        String(32), default="success", server_default="success"
    )
    request_id: Mapped[str] = mapped_column(String(36), default="", server_default="")
    actor: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str] = mapped_column(String(160))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
