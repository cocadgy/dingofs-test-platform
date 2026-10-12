from sqlalchemy import Boolean, Index, JSON, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from dingofs_platform.db import Base, Record


class StorageProfile(Record, Base):
    __tablename__ = "storage_profiles"
    __table_args__ = (
        Index(
            "uq_storage_profile_active_name", "name", unique=True,
            postgresql_where=text("deleted = false"),
        ),
    )

    creator_id: Mapped[str] = mapped_column(String(36))
    name: Mapped[str] = mapped_column(String(120))
    storage_type: Mapped[str] = mapped_column(String(16))
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    parameters: Mapped[dict] = mapped_column(JSON)
    secret_ciphertext: Mapped[str] = mapped_column(Text)
