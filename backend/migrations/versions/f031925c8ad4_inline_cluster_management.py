"""Copy management settings onto each cluster; retire the separate context workflow.

Keep historical context rows untouched for recovery, including unreferenced ones.
"""

from alembic import op
import sqlalchemy as sa
from uuid import uuid4

revision = "f031925c8ad4"
down_revision = "e9f218b704c2"
branch_labels = None
depends_on = None
FIELDS = (
    "management_machine_id",
    "os_user",
    "dingo_path",
    "config_dir",
    "credential_ref",
)


def upgrade():
    for name, length in zip(FIELDS, (36, 80, 512, 512, 160)):
        op.add_column("clusters", sa.Column(name, sa.String(length), nullable=True))
    op.execute("""UPDATE clusters AS c SET management_machine_id = m.machine_id,
        os_user = m.os_user, dingo_path = m.dingo_path, config_dir = m.config_dir,
        credential_ref = m.credential_ref FROM management_contexts AS m
        WHERE c.context_id = m.id""")
    for name in FIELDS:
        op.alter_column("clusters", name, nullable=False)
    inspector = sa.inspect(op.get_bind())
    for constraint in inspector.get_unique_constraints("clusters"):
        if "context_id" in constraint["column_names"]:
            op.drop_constraint(constraint["name"], "clusters", type_="unique")
    for constraint in inspector.get_foreign_keys("clusters"):
        if constraint["constrained_columns"] == ["context_id"]:
            op.drop_constraint(constraint["name"], "clusters", type_="foreignkey")
    op.drop_column("clusters", "context_id")
    op.create_foreign_key(
        "clusters_management_machine_id_fkey",
        "clusters",
        "machines",
        ["management_machine_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_cluster_management_identity",
        "clusters",
        ["management_machine_id", "os_user", "config_dir", "external_name"],
    )


def downgrade():
    # The old schema cannot represent different tool/credential settings for the
    # same machine/user/directory. Refuse rather than silently overwrite them.
    db = op.get_bind()
    rows = db.execute(sa.text("SELECT * FROM clusters ORDER BY id")).mappings().all()
    contexts = db.execute(sa.text("SELECT * FROM management_contexts")).mappings().all()
    by_identity = {
        (r["machine_id"], r["os_user"], r["config_dir"]): dict(r) for r in contexts
    }
    for row in rows:
        key = (row["management_machine_id"], row["os_user"], row["config_dir"])
        existing = by_identity.get(key)
        if existing and any(
            existing[f] != row[f] for f in ("dingo_path", "credential_ref")
        ):
            raise RuntimeError(
                "Cannot downgrade independently edited cluster settings without losing data; restore a pre-upgrade backup instead."
            )
        by_identity.setdefault(key, dict(row))
    op.add_column("clusters", sa.Column("context_id", sa.String(36), nullable=True))
    by_identity = {
        (r["machine_id"], r["os_user"], r["config_dir"]): dict(r) for r in contexts
    }
    for row in rows:
        key = (row["management_machine_id"], row["os_user"], row["config_dir"])
        context = by_identity.get(key)
        if not context:
            cid = str(uuid4())
            context = dict(
                row,
                id=cid,
                machine_id=row["management_machine_id"],
                name="restored-" + cid,
            )
            db.execute(
                sa.text("""INSERT INTO management_contexts
                (id, name, machine_id, os_user, dingo_path, config_dir, credential_ref,
                 archived, created_at, updated_at, revision)
                VALUES (:id, :name, :machine_id, :os_user, :dingo_path, :config_dir,
                        :credential_ref, :archived, :created_at, :updated_at, :revision)"""),
                context,
            )
            by_identity[key] = context
        db.execute(
            sa.text("UPDATE clusters SET context_id=:cid WHERE id=:id"),
            dict(cid=context["id"], id=row["id"]),
        )
    op.alter_column("clusters", "context_id", nullable=False)
    op.create_foreign_key(
        "clusters_context_id_fkey",
        "clusters",
        "management_contexts",
        ["context_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "clusters_context_id_external_name_key",
        "clusters",
        ["context_id", "external_name"],
    )
    op.drop_constraint("uq_cluster_management_identity", "clusters", type_="unique")
    op.drop_constraint(
        "clusters_management_machine_id_fkey", "clusters", type_="foreignkey"
    )
    for name in reversed(FIELDS):
        op.drop_column("clusters", name)
