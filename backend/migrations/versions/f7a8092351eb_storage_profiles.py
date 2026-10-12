"""Shared storage profiles with write-only encrypted credentials."""

from alembic import op
import sqlalchemy as sa

revision = "f7a8092351eb"
down_revision = "f697f81240da"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "storage_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("creator_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("storage_type", sa.String(16), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
    )
    op.create_index(
        "uq_storage_profile_active_name", "storage_profiles", ["name"],
        unique=True, postgresql_where=sa.text("deleted = false"),
    )


def downgrade():
    op.drop_table("storage_profiles")
