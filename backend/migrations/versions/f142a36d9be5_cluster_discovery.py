"""Cluster observations and discoverable non-global names."""

from alembic import op
import sqlalchemy as sa

revision = "f142a36d9be5"
down_revision = "f031925c8ad4"
branch_labels = None
depends_on = None


def upgrade():
    for c in [
        sa.Column(
            "binding_state", sa.String(24), nullable=False, server_default="legacy"
        ),
        sa.Column("execution_home", sa.String(512)),
        sa.Column("resolved_dingo_path", sa.String(512)),
        sa.Column("status_snapshot", sa.JSON()),
        sa.Column("status_success_at", sa.DateTime(timezone=True)),
        sa.Column("status_attempt_at", sa.DateTime(timezone=True)),
        sa.Column(
            "status_attempt_state",
            sa.String(24),
            nullable=False,
            server_default="never",
        ),
        sa.Column("status_error_code", sa.String(80)),
        sa.Column("status_output", sa.JSON()),
    ]:
        op.add_column("clusters", c)
    for c in sa.inspect(op.get_bind()).get_unique_constraints("clusters"):
        if c["column_names"] == ["name"]:
            op.drop_constraint(c["name"], "clusters", type_="unique")
    op.create_table(
        "cluster_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column(
            "machine_id", sa.String(36), sa.ForeignKey("machines.id"), nullable=False
        ),
        sa.Column("machine_revision", sa.Integer(), nullable=False),
        sa.Column("target_user", sa.String(80), nullable=False),
        sa.Column("cluster_id", sa.String(36), sa.ForeignKey("clusters.id")),
        sa.Column("cluster_revision", sa.Integer()),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("lease_token", sa.String(64), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("challenge_digest", sa.String(64)),
        sa.Column("auth_account", sa.String(80)),
        sa.Column("auth_attempts", sa.Integer(), nullable=False),
    )


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text("SELECT name FROM clusters GROUP BY name HAVING count(*)>1 LIMIT 1")
        )
        .first()
    ):
        raise RuntimeError(
            "Cannot downgrade duplicate cluster names without losing data"
        )
    op.drop_table("cluster_operations")
    op.create_unique_constraint("clusters_name_key", "clusters", ["name"])
    for name in [
        "status_output",
        "status_error_code",
        "status_attempt_state",
        "status_attempt_at",
        "status_success_at",
        "status_snapshot",
        "resolved_dingo_path",
        "execution_home",
        "binding_state",
    ]:
        op.drop_column("clusters", name)
