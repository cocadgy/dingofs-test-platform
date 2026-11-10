"""Persist idempotent functional parents, module execution and shared leases."""
from alembic import op
import sqlalchemy as sa

revision = '7b1c9e4a602d'
down_revision = '2f6d6db8c141'
branch_labels = None
depends_on = None


def record_columns():
    return [sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('revision', sa.Integer(), nullable=False)]


def upgrade():
    op.drop_index('uq_functional_active_cluster', table_name='functional_runs')
    op.add_column('functional_runs', sa.Column('version', sa.Integer(), server_default='1', nullable=False))
    # Preserve legacy API concurrency safety while permitting a V2 queue.
    op.create_index('uq_functional_legacy_active_cluster', 'functional_runs', ['cluster_id'], unique=True,
                    postgresql_where=sa.text("version = 1 AND state IN ('queued','running','cancelling','unknown')"))
    op.add_column('functional_runs', sa.Column('idempotency_key', sa.String(128), nullable=True))
    op.add_column('functional_runs', sa.Column('request_digest', sa.String(64), nullable=True))
    op.alter_column('functional_runs', 'deadline', existing_type=sa.DateTime(timezone=True), nullable=True)
    op.create_unique_constraint('uq_functional_idempotency', 'functional_runs', ['creator_id', 'idempotency_key'])
    op.create_table('functional_module_runs', *record_columns(),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('functional_runs.id'), nullable=False),
        sa.Column('module', sa.String(40), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(24), nullable=False),
        sa.Column('environment_snapshot', sa.JSON(), nullable=False),
        sa.Column('cases', sa.JSON(), nullable=False),
        sa.Column('case_hashes', sa.JSON(), nullable=False),
        sa.Column('timeout_minutes', sa.Integer(), nullable=False),
        sa.Column('retries', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deadline', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancel_requested', sa.Boolean(), nullable=False),
        sa.Column('cancel_requested_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('launch_attempted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('remote_identity', sa.JSON(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False),
        sa.Column('error', sa.Text(), nullable=False),
        sa.UniqueConstraint('run_id', 'module', name='uq_functional_child_module'),
        sa.UniqueConstraint('run_id', 'position', name='uq_functional_child_position'),
        sa.CheckConstraint('position >= 0', name='ck_functional_child_position'),
        sa.CheckConstraint('timeout_minutes BETWEEN 1 AND 1440', name='ck_functional_child_timeout'),
        sa.CheckConstraint('retries BETWEEN 0 AND 5', name='ck_functional_child_retries'))
    op.create_table('functional_preflights', *record_columns(),
        sa.Column('creator_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('request_digest', sa.String(64), nullable=False),
        sa.Column('source_digest', sa.String(64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('checks', sa.JSON(), nullable=False),
        sa.Column('required_confirmations', sa.JSON(), nullable=False),
        sa.Column('can_start', sa.Boolean(), nullable=False),
        sa.Column('consumed_by', sa.String(36), sa.ForeignKey('functional_runs.id'), nullable=True))
    op.create_table('functional_events', *record_columns(),
        sa.Column('child_id', sa.String(36), sa.ForeignKey('functional_module_runs.id'), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('record', sa.JSON(), nullable=False),
        sa.UniqueConstraint('child_id', 'seq', name='uq_functional_event_seq'),
        sa.CheckConstraint('seq > 0', name='ck_functional_event_seq'))
    op.create_table('functional_resources', *record_columns(),
        sa.Column('child_id', sa.String(36), sa.ForeignKey('functional_module_runs.id'), nullable=False),
        sa.Column('resource_id', sa.String(128), nullable=False),
        sa.Column('kind', sa.String(80), nullable=False),
        sa.Column('cluster', sa.String(255), nullable=False),
        sa.Column('host', sa.String(255), nullable=True),
        sa.Column('user', sa.String(120), nullable=True),
        sa.Column('name', sa.Text(), nullable=True),
        sa.Column('path', sa.Text(), nullable=True),
        sa.Column('port', sa.Integer(), nullable=True),
        sa.Column('owned', sa.Boolean(), nullable=False),
        sa.Column('phase', sa.String(16), nullable=False),
        sa.Column('remote_identity', sa.JSON(), nullable=False),
        sa.UniqueConstraint('child_id', 'resource_id', name='uq_functional_resource'),
        sa.CheckConstraint("phase IN ('intent','active','retained','removed','unknown')", name='ck_functional_resource_phase'))
    op.create_table('operation_leases', *record_columns(),
        sa.Column('key', sa.String(512), nullable=False),
        sa.Column('owner', sa.String(128), nullable=False),
        sa.Column('mode', sa.String(16), nullable=False),
        sa.Column('depth', sa.Integer(), nullable=False),
        sa.Column('acquired_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('key', 'owner', 'mode', name='uq_operation_lease_owner_mode'),
        sa.CheckConstraint("mode IN ('shared','exclusive')", name='ck_operation_lease_mode'),
        sa.CheckConstraint('depth >= 0', name='ck_operation_lease_depth'))
    op.create_index('ix_operation_lease_key_released', 'operation_leases', ['key', 'released_at'])


def downgrade():
    # A downgrade cannot represent queued module runs or their NULL deadlines.
    # Refuse before deleting anything; operators must explicitly archive/export.
    connection = op.get_bind()
    if connection.execute(sa.text('SELECT 1 FROM functional_runs WHERE version = 2 LIMIT 1')).first():
        raise RuntimeError('Cannot downgrade while guided functional runs exist')
    for table in ('operation_leases', 'functional_resources', 'functional_events',
                  'functional_preflights', 'functional_module_runs'):
        op.drop_table(table)
    op.drop_constraint('uq_functional_idempotency', 'functional_runs', type_='unique')
    op.drop_index('uq_functional_legacy_active_cluster', table_name='functional_runs')
    for column in ('request_digest', 'idempotency_key', 'version'):
        op.drop_column('functional_runs', column)
    op.alter_column('functional_runs', 'deadline', existing_type=sa.DateTime(timezone=True), nullable=False)
    op.create_index('uq_functional_active_cluster', 'functional_runs', ['cluster_id'], unique=True,
                    postgresql_where=sa.text("state IN ('queued','running','cancelling','unknown')"))
