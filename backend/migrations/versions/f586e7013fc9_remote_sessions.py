"""Persistent remote session authorization and lifecycle metadata."""

from alembic import op
import sqlalchemy as sa

revision = "f586e7013fc9"
down_revision = "f475d6902eb8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "remote_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("login_session_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column(
            "cluster_id", sa.String(36), sa.ForeignKey("clusters.id"), nullable=False
        ),
        sa.Column(
            "machine_id", sa.String(36), sa.ForeignKey("machines.id"), nullable=False
        ),
        sa.Column("cluster_revision", sa.Integer(), nullable=False),
        sa.Column("machine_revision", sa.Integer(), nullable=False),
        sa.Column("target_user", sa.String(80), nullable=False),
        sa.Column("service_id", sa.String(160)),
        sa.Column("log_root", sa.String(4096)),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("auth_account", sa.String(80)),
        sa.Column("auth_attempts", sa.Integer(), nullable=False),
        sa.Column("challenge_hash", sa.String(64)),
        sa.Column("auth_expires_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(80)),
        sa.Column("result", sa.JSON()),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
    )
    for field in ("actor_id", "machine_id", "state"):
        op.create_index("ix_remote_sessions_" + field, "remote_sessions", [field])


def downgrade():
    op.drop_table("remote_sessions")
