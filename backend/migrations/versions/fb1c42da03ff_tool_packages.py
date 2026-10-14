"""Tool bundles and bounded machine deployment jobs."""
from alembic import op
import sqlalchemy as sa
revision = 'fb1c42da03ff'
down_revision = 'fa0b31c902ef'
branch_labels = None
depends_on = None


def common():
    return [sa.Column('id', sa.String(36), primary_key=True), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False), sa.Column('revision', sa.Integer(), nullable=False)]


def upgrade():
    op.create_table('tool_packages', *common(), sa.Column('creator_id', sa.String(36), nullable=False), sa.Column('tool', sa.String(32), nullable=False), sa.Column('version', sa.String(80), nullable=False), sa.Column('architecture', sa.String(24), nullable=False), sa.Column('directory', sa.String(512), nullable=False), sa.Column('digest', sa.String(64), unique=True, nullable=False), sa.Column('size_bytes', sa.BigInteger(), nullable=False), sa.Column('manifest', sa.JSON(), nullable=False))
    op.create_table('tool_jobs', *common(), sa.Column('machine_id', sa.String(36), sa.ForeignKey('machines.id'), nullable=False), sa.Column('creator_id', sa.String(36), nullable=False), sa.Column('package_id', sa.String(36), sa.ForeignKey('tool_packages.id')), sa.Column('action', sa.String(16), nullable=False), sa.Column('state', sa.String(24), nullable=False), sa.Column('phase', sa.String(80), nullable=False), sa.Column('progress', sa.Integer(), nullable=False), sa.Column('log', sa.Text(), nullable=False), sa.Column('result', sa.JSON()), sa.Column('deadline', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table('tool_jobs')
    op.drop_table('tool_packages')
