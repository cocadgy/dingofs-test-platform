"""Record creators without assigning legacy resources to an arbitrary user."""

from alembic import op
import sqlalchemy as sa

revision = "f253b47e0cf6"
down_revision = "f142a36d9be5"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("machines", "clusters"):
        op.add_column(table, sa.Column("creator_id", sa.String(36), nullable=True))


def downgrade():
    for table in ("clusters", "machines"):
        op.drop_column(table, "creator_id")
