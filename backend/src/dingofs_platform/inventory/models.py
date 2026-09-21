from sqlalchemy import (
    String,
    Boolean,
    JSON,
    ForeignKey,
    UniqueConstraint,
    Table,
    Column,
)
from sqlalchemy.orm import Mapped, mapped_column
from dingofs_platform.db import Base, Record


class Asset(Record):
    name: Mapped[str] = mapped_column(String(120), unique=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Machine(Asset, Base):
    __tablename__ = "machines"
    address: Mapped[str] = mapped_column(String(255))
    ssh_port: Mapped[int] = mapped_column(default=22)
    ssh_user: Mapped[str] = mapped_column(String(80))
    credential_ref: Mapped[str] = mapped_column(String(160), default="")
    physical_id: Mapped[str | None] = mapped_column(
        String(160), unique=True, nullable=True
    )
    tags: Mapped[list] = mapped_column(JSON, default=list)
    maintenance: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("address", "ssh_port"),)


class ManagementContext(Asset, Base):
    __tablename__ = "management_contexts"
    machine_id: Mapped[str] = mapped_column(ForeignKey("machines.id"))
    os_user: Mapped[str] = mapped_column(String(80))
    dingo_path: Mapped[str] = mapped_column(String(512))
    config_dir: Mapped[str] = mapped_column(String(512))
    credential_ref: Mapped[str] = mapped_column(String(160), default="")
    __table_args__ = (UniqueConstraint("machine_id", "os_user", "config_dir"),)


class Cluster(Asset, Base):
    __tablename__ = "clusters"
    context_id: Mapped[str] = mapped_column(ForeignKey("management_contexts.id"))
    external_name: Mapped[str] = mapped_column(String(120))
    management_scope: Mapped[str] = mapped_column(String(30), default="registered")
    observed_state: Mapped[str] = mapped_column(String(30), default="unknown")
    __table_args__ = (UniqueConstraint("context_id", "external_name"),)


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
