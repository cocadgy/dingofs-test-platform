"""Persist resumable functional wizard drafts."""
from alembic import op
import sqlalchemy as sa
revision='2f6d6db8c141'
down_revision='ff5c8d9a7b31'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('functional_drafts',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('creator_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('name',sa.String(120),nullable=False),
        sa.Column('step',sa.Integer(),nullable=False),
        sa.Column('configuration',sa.JSON(),nullable=False),
        sa.Column('state',sa.String(20),nullable=False),
        sa.Column('run_id',sa.String(36),sa.ForeignKey('functional_runs.id'),nullable=True))
    op.create_index('ix_functional_drafts_owner_state','functional_drafts',['creator_id','state'])

def downgrade():
    op.drop_index('ix_functional_drafts_owner_state',table_name='functional_drafts')
    op.drop_table('functional_drafts')
