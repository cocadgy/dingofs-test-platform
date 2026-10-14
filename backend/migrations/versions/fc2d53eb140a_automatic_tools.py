"""Web-managed tool source and automatic deployments."""
from alembic import op
import sqlalchemy as sa
revision='fc2d53eb140a'
down_revision='fb1c42da03ff'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('tool_jobs',sa.Column('options',sa.JSON(),nullable=True))
    op.create_table('tool_sources',sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('machine_id',sa.String(36),sa.ForeignKey('machines.id'),nullable=False),
        sa.Column('directory',sa.String(512),nullable=False),
        sa.Column('image',sa.String(512),nullable=False),sa.Column('allow_cached',sa.Boolean(),nullable=False))


def downgrade():
    op.drop_table('tool_sources')
    op.drop_column('tool_jobs','options')
