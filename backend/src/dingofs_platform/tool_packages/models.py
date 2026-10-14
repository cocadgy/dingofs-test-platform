from sqlalchemy import JSON, String, Text, ForeignKey, BigInteger, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from dingofs_platform.db import Base, Record


class ToolPackage(Record, Base):
    __tablename__ = 'tool_packages'
    creator_id: Mapped[str] = mapped_column(String(36))
    tool: Mapped[str] = mapped_column(String(32))
    version: Mapped[str] = mapped_column(String(80))
    architecture: Mapped[str] = mapped_column(String(24))
    directory: Mapped[str] = mapped_column(String(512))
    digest: Mapped[str] = mapped_column(String(64), unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    manifest: Mapped[dict] = mapped_column(JSON)


class ToolJob(Record, Base):
    __tablename__ = 'tool_jobs'
    machine_id: Mapped[str] = mapped_column(ForeignKey('machines.id'))
    creator_id: Mapped[str] = mapped_column(String(36))
    package_id: Mapped[str | None] = mapped_column(ForeignKey('tool_packages.id'), nullable=True)
    options: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    action: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(24), default='running')
    phase: Mapped[str] = mapped_column(String(80), default='连接机器')
    progress: Mapped[int] = mapped_column(default=0)
    log: Mapped[str] = mapped_column(Text, default='')
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ToolSource(Record, Base):
    __tablename__ = 'tool_sources'
    machine_id: Mapped[str] = mapped_column(ForeignKey('machines.id'))
    directory: Mapped[str] = mapped_column(String(512))
    image: Mapped[str] = mapped_column(String(512))
    allow_cached: Mapped[bool] = mapped_column(default=False)
