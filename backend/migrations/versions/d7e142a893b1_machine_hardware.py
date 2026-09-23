"""Write-only credentials and hardware observations."""

from alembic import op
import sqlalchemy as sa

revision = "d7e142a893b1"
down_revision = "c69f129b82a0"
branch_labels = None
depends_on = None


def upgrade():
    for name, kind in [
        ("ssh_password_ciphertext", sa.Text()),
        ("hardware_info", sa.JSON()),
        ("last_attempt_info", sa.JSON()),
        ("last_attempt_at", sa.DateTime(timezone=True)),
        ("last_success_at", sa.DateTime(timezone=True)),
        ("collection_error", sa.String(512)),
        ("collection_token", sa.String(36)),
        ("collection_expires_at", sa.DateTime(timezone=True)),
    ]:
        op.add_column("machines", sa.Column(name, kind, nullable=True))
    op.add_column(
        "machines",
        sa.Column(
            "collection_status", sa.String(24), server_default="never", nullable=False
        ),
    )


def downgrade():
    for name in [
        "collection_status",
        "collection_expires_at",
        "collection_token",
        "collection_error",
        "last_success_at",
        "last_attempt_at",
        "last_attempt_info",
        "hardware_info",
        "ssh_password_ciphertext",
    ]:
        op.drop_column("machines", name)
