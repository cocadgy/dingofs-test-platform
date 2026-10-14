"""Allow SSH terminal sessions on inventory machines without a cluster."""

from alembic import op
import sqlalchemy as sa

revision = "fa0b31c902ef"
down_revision = "f9ca214573ad"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("remote_sessions", "cluster_id", existing_type=sa.String(36), nullable=True)
    op.alter_column("remote_sessions", "cluster_revision", existing_type=sa.Integer(), nullable=True)


def downgrade():
    op.execute("DELETE FROM remote_sessions WHERE cluster_id IS NULL")
    op.alter_column("remote_sessions", "cluster_revision", existing_type=sa.Integer(), nullable=False)
    op.alter_column("remote_sessions", "cluster_id", existing_type=sa.String(36), nullable=False)
