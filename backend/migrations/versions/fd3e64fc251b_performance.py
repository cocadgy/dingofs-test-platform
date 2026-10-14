"""Durable single-client performance runs."""
from alembic import op
import sqlalchemy as sa
revision='fd3e64fc251b'
down_revision='fc2d53eb140a'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('performance_runs',
        sa.Column('id',sa.String(36),primary_key=True),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('creator_id',sa.String(36),nullable=False),sa.Column('machine_id',sa.String(36),sa.ForeignKey('machines.id'),nullable=False),
        sa.Column('name',sa.String(120),nullable=False),sa.Column('state',sa.String(24),nullable=False),
        sa.Column('phase',sa.String(160),nullable=False),sa.Column('progress',sa.Integer(),nullable=False),
        sa.Column('snapshot',sa.JSON(),nullable=False),sa.Column('log',sa.Text(),nullable=False),
        sa.Column('error',sa.Text(),nullable=False),sa.Column('reports',sa.JSON(),nullable=False),
        sa.Column('remote_root',sa.Text(),nullable=True),sa.Column('cancel_requested',sa.Boolean(),nullable=False),
        sa.Column('deadline',sa.DateTime(timezone=True),nullable=False),sa.Column('finished_at',sa.DateTime(timezone=True),nullable=True))
    op.create_index('uq_performance_active_machine','performance_runs',['machine_id'],unique=True,
                    postgresql_where=sa.text("state IN ('queued','running','cancelling','unknown')"))


def downgrade():
    op.drop_table('performance_runs')
