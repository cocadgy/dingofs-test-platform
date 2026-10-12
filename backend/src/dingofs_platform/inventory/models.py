from sqlalchemy import (
    String,
    Text,
    DateTime,
    Boolean,
    JSON,
    ForeignKey,
    UniqueConstraint,
    Table,
    Column,
)
from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column
from dingofs_platform.db import Base, Record


class Asset(Record):
    name: Mapped[str] = mapped_column(String(120), unique=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Machine(Asset, Base):
    __tablename__ = "machines"
    creator_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    address: Mapped[str] = mapped_column(String(255))
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    ssh_port: Mapped[int] = mapped_column(default=22)
    ssh_user: Mapped[str] = mapped_column(String(80))
    credential_ref: Mapped[str] = mapped_column(String(160), default="")
    ssh_password_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    ssh_host_key: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ssh_trust_pending: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    hardware_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_attempt_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    collection_status: Mapped[str] = mapped_column(
        String(24), default="never", server_default="never"
    )
    collection_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    collection_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    collection_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    physical_id: Mapped[str | None] = mapped_column(
        String(160), unique=True, nullable=True
    )
    tags: Mapped[list] = mapped_column(JSON, default=list)
    maintenance: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("address", "ssh_port"),)


class MachineHostIdentifier(Base):
    """Canonical addresses and aliases; uniqueness is per machine, not global."""

    __tablename__ = "machine_host_identifiers"
    machine_id: Mapped[str] = mapped_column(
        ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True
    )
    identifier: Mapped[str] = mapped_column(String(255), primary_key=True, index=True)


class LegacyManagementContext(Asset, Base):
    """Historical records retained for recovery; no longer exposed or referenced."""

    __tablename__ = "management_contexts"
    machine_id: Mapped[str] = mapped_column(ForeignKey("machines.id"))
    os_user: Mapped[str] = mapped_column(String(80))
    dingo_path: Mapped[str] = mapped_column(String(512))
    config_dir: Mapped[str] = mapped_column(String(512))
    credential_ref: Mapped[str] = mapped_column(String(160), default="")
    __table_args__ = (UniqueConstraint("machine_id", "os_user", "config_dir"),)


class Cluster(Asset, Base):
    __tablename__ = "clusters"
    creator_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    binding_state: Mapped[str] = mapped_column(
        String(24), default="legacy", server_default="legacy"
    )
    execution_home: Mapped[str | None] = mapped_column(String(512))
    resolved_dingo_path: Mapped[str | None] = mapped_column(String(512))
    status_snapshot: Mapped[dict | None] = mapped_column(JSON)
    status_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_attempt_state: Mapped[str] = mapped_column(
        String(24), default="never", server_default="never"
    )
    status_error_code: Mapped[str | None] = mapped_column(String(80))
    status_output: Mapped[dict | None] = mapped_column(JSON)
    management_machine_id: Mapped[str] = mapped_column(ForeignKey("machines.id"))
    os_user: Mapped[str] = mapped_column(String(80))
    dingo_path: Mapped[str] = mapped_column(String(512))
    config_dir: Mapped[str] = mapped_column(String(512))
    credential_ref: Mapped[str] = mapped_column(String(160), default="")
    external_name: Mapped[str] = mapped_column(String(120))
    management_scope: Mapped[str] = mapped_column(String(30), default="registered")
    observed_state: Mapped[str] = mapped_column(String(30), default="unknown")
    __table_args__ = (
        UniqueConstraint(
            "management_machine_id",
            "os_user",
            "config_dir",
            "external_name",
            name="uq_cluster_management_identity",
        ),
    )


class Environment(Asset, Base):
    __tablename__ = "environments"
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


cluster_machines = Table(
    "cluster_machines",
    Base.metadata,
    Column("role", String(32), nullable=False, server_default="unclassified"),
    Column("managed", Boolean, nullable=False, server_default="false"),
    Column("cluster_id", ForeignKey("clusters.id"), primary_key=True),
    Column("machine_id", ForeignKey("machines.id"), primary_key=True),
)
environment_machines = Table(
    "environment_machines",
    Base.metadata,
    Column("role", String(32), nullable=False, server_default="client"),
    Column("environment_id", ForeignKey("environments.id"), primary_key=True),
    Column("machine_id", ForeignKey("machines.id"), primary_key=True),
)
