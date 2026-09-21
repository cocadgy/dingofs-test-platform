from sqlalchemy import String, Text, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from dingofs_platform.db import Base, Record


class ConfigDraft(Record, Base):
    __tablename__ = "config_drafts"
    owner_kind: Mapped[str] = mapped_column(String(32))
    owner_id: Mapped[str] = mapped_column(String(36))
    yaml_text: Mapped[str] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("owner_kind", "owner_id"),)


class ConfigVersion(Record, Base):
    __tablename__ = "config_versions"
    owner_kind: Mapped[str] = mapped_column(String(32))
    owner_id: Mapped[str] = mapped_column(String(36))
    version: Mapped[int] = mapped_column(Integer)
    yaml_text: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    author: Mapped[str] = mapped_column(String(36))
    __table_args__ = (UniqueConstraint("owner_kind", "owner_id", "version"),)
