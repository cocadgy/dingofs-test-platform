"""Versioned cache parameter profiles."""

from alembic import op
import sqlalchemy as sa

revision = "f8b9103462fc"
down_revision = "f7a8092351eb"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cache_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("creator_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("source_version", sa.String(80), nullable=False),
    )
    op.create_index(
        "uq_cache_profile_active_name", "cache_profiles", ["name"],
        unique=True, postgresql_where=sa.text("deleted = false"),
    )


def downgrade():
    op.drop_table("cache_profiles")
