"""Add required-on-write user email; preserve existing accounts for owner completion."""

from alembic import op
import sqlalchemy as sa

revision = "c69f129b82a0"
down_revision = "b414037149a5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("email", sa.String(254), nullable=True))


def downgrade():
    op.drop_column("users", "email")
