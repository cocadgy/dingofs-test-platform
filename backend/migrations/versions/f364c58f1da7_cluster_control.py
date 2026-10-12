"""Persist the confirmed target of cluster service controls."""

from alembic import op
import sqlalchemy as sa

revision = "f364c58f1da7"
down_revision = "f253b47e0cf6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cluster_operations", sa.Column("parameters", sa.JSON(), nullable=True)
    )


def downgrade():
    op.drop_column("cluster_operations", "parameters")
