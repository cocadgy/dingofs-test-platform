"""Versioned functional test environment profiles."""
from alembic import op
import sqlalchemy as sa
revision='ff5c8d9a7b31'
down_revision='fe4b69d26a10'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('functional_environment_profiles',
      sa.Column('id',sa.String(36),primary_key=True),
      sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
      sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
      sa.Column('revision',sa.Integer(),nullable=False),
      sa.Column('creator_id',sa.String(36),nullable=True),
      sa.Column('name',sa.String(120),nullable=False),
      sa.Column('source_kind',sa.String(16),nullable=False),
      sa.Column('source_file',sa.String(255),nullable=True),
      sa.Column('source_key',sa.String(120),nullable=True),
      sa.Column('source_digest',sa.String(64),nullable=True),
      sa.Column('cluster_id',sa.String(36),sa.ForeignKey('clusters.id'),nullable=True),
      sa.Column('machine_id',sa.String(36),sa.ForeignKey('machines.id'),nullable=True),
      sa.Column('storage_profile_id',sa.String(36),sa.ForeignKey('storage_profiles.id'),nullable=True),
      sa.Column('storage_profile_revision',sa.Integer(),nullable=True),
      sa.Column('settings',sa.JSON(),nullable=False),
      sa.Column('display',sa.JSON(),nullable=False),
      sa.Column('enabled',sa.Boolean(),nullable=False),
      sa.Column('deleted',sa.Boolean(),nullable=False),
      sa.Column('validation',sa.String(32),nullable=False))
    op.create_index('uq_functional_environment_active_name','functional_environment_profiles',['name'],unique=True,
      postgresql_where=sa.text('deleted = false'))
    op.create_index('uq_functional_environment_source','functional_environment_profiles',['source_file','source_key'],unique=True,
      postgresql_where=sa.text("source_kind = 'predefined'"))

def downgrade():
    op.drop_table('functional_environment_profiles')
