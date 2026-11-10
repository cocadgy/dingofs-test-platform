"""Versioned, secret-free functional test environment profiles."""
from sqlalchemy import Boolean, ForeignKey, Index, JSON, String, text
from sqlalchemy.orm import Mapped, mapped_column
from dingofs_platform.db import Base, Record

class FunctionalEnvironmentProfile(Record, Base):
    __tablename__ = 'functional_environment_profiles'
    __table_args__ = (
        Index('uq_functional_environment_active_name', 'name', unique=True,
              postgresql_where=text('deleted = false')),
        Index('uq_functional_environment_source', 'source_file', 'source_key', unique=True,
              postgresql_where=text("source_kind = 'predefined'")),
    )
    creator_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    source_kind: Mapped[str] = mapped_column(String(16))
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cluster_id: Mapped[str | None] = mapped_column(ForeignKey('clusters.id'), nullable=True)
    machine_id: Mapped[str | None] = mapped_column(ForeignKey('machines.id'), nullable=True)
    storage_profile_id: Mapped[str | None] = mapped_column(ForeignKey('storage_profiles.id'), nullable=True)
    storage_profile_revision: Mapped[int | None] = mapped_column(nullable=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    display: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    validation: Mapped[str] = mapped_column(String(32), default='needs_validation')
