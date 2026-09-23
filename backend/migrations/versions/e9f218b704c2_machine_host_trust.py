"""Persist explicitly approved SSH host keys and expiring challenges."""

from alembic import op
import sqlalchemy as sa

revision = "e9f218b704c2"
down_revision = "d7e142a893b1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("machines", sa.Column("ssh_host_key", sa.JSON(), nullable=True))
    op.add_column("machines", sa.Column("ssh_trust_pending", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("machines", "ssh_trust_pending")
    op.drop_column("machines", "ssh_host_key")
