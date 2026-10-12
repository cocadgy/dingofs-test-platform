"""Managed filesystems/cache deployments/mount operations."""

from alembic import op
import sqlalchemy as sa

revision = "f697f81240da"
down_revision = "f586e7013fc9"
branch_labels = None
depends_on = None


def record():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
    ]


def upgrade():
    op.create_table(
        "managed_resources",
        *record(),
        sa.Column(
            "cluster_id", sa.String(36), sa.ForeignKey("clusters.id"), nullable=False
        ),
        sa.Column("creator_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(4096), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_managed_resources_cluster_id", "managed_resources", ["cluster_id"]
    )
    op.create_table(
        "resource_operations",
        *record(),
        sa.Column(
            "cluster_id", sa.String(36), sa.ForeignKey("clusters.id"), nullable=False
        ),
        sa.Column("cluster_revision", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("secret_ciphertext", sa.Text()),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("cursor", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.String(36), sa.ForeignKey("managed_resources.id")),
        sa.Column("result", sa.JSON()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("lease_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("auth_account", sa.String(80)),
        sa.Column("challenge_digest", sa.String(64)),
        sa.Column("auth_attempts", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "actor_id", "cluster_id", "request_id", name="uq_resource_request"
        ),
    )
    op.create_index(
        "ix_resource_operations_cluster_id", "resource_operations", ["cluster_id"]
    )


def downgrade():
    op.drop_table("resource_operations")
    op.drop_table("managed_resources")
