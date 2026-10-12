"""Index explicit machine addresses and aliases for unambiguous host matching."""

import ipaddress

import sqlalchemy as sa
from alembic import op

revision = "f475d6902eb8"
down_revision = "f364c58f1da7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "machines", sa.Column("aliases", sa.JSON(), nullable=False, server_default="[]")
    )
    table = op.create_table(
        "machine_host_identifiers",
        sa.Column("machine_id", sa.String(36), nullable=False),
        sa.Column("identifier", sa.String(255), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("machine_id", "identifier"),
    )
    op.create_index(
        "ix_machine_host_identifiers_identifier",
        "machine_host_identifiers",
        ["identifier"],
    )
    connection = op.get_bind()
    for machine in connection.execute(sa.text("SELECT id, address FROM machines")):
        # Preserve connection addresses and host-key trust exactly as registered.
        # Legacy hostname validation was permissive; backfill without rejecting it.
        identifier = machine.address.strip().lower().removesuffix(".")
        try:
            identifier = str(ipaddress.ip_address(identifier))
        except ValueError:
            pass
        connection.execute(
            table.insert().values(machine_id=machine.id, identifier=identifier)
        )


def downgrade():
    op.drop_index(
        "ix_machine_host_identifiers_identifier", table_name="machine_host_identifiers"
    )
    op.drop_table("machine_host_identifiers")
    op.drop_column("machines", "aliases")
