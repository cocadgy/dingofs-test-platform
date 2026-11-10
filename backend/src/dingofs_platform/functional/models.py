from datetime import datetime
from sqlalchemy import JSON,DateTime,ForeignKey,String,Text,Index,UniqueConstraint,CheckConstraint,event,inspect,text
from sqlalchemy.orm import Mapped,mapped_column
from dingofs_platform.db import Base,Record
ACTIVE=('queued','running','cancelling','unknown')
class FunctionalRun(Record,Base):
    __tablename__='functional_runs'
    creator_id:Mapped[str]=mapped_column(String(36))
    cluster_id:Mapped[str]=mapped_column(ForeignKey('clusters.id'))
    machine_id:Mapped[str]=mapped_column(ForeignKey('machines.id'))
    name:Mapped[str]=mapped_column(String(120))
    state:Mapped[str]=mapped_column(String(24),default='queued')
    phase:Mapped[str]=mapped_column(String(160),default='等待执行')
    progress:Mapped[int]=mapped_column(default=0)
    snapshot:Mapped[dict]=mapped_column(JSON)
    log:Mapped[str]=mapped_column(Text,default='')
    error:Mapped[str]=mapped_column(Text,default='')
    result:Mapped[dict]=mapped_column(JSON,default=dict)
    remote_root:Mapped[str|None]=mapped_column(Text,nullable=True)
    cancel_requested:Mapped[bool]=mapped_column(default=False)
    deadline:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    finished_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    version:Mapped[int]=mapped_column(default=1,server_default='1')
    idempotency_key:Mapped[str|None]=mapped_column(String(128),nullable=True)
    request_digest:Mapped[str|None]=mapped_column(String(64),nullable=True)
    __table_args__=(
        UniqueConstraint('creator_id','idempotency_key',name='uq_functional_idempotency'),
        Index('uq_functional_legacy_active_cluster','cluster_id',unique=True,
              postgresql_where=text("version = 1 AND state IN ('queued','running','cancelling','unknown')")),
    )


class FunctionalModuleRun(Record,Base):
    __tablename__='functional_module_runs'
    run_id:Mapped[str]=mapped_column(ForeignKey('functional_runs.id'))
    module:Mapped[str]=mapped_column(String(40))
    position:Mapped[int]=mapped_column()
    state:Mapped[str]=mapped_column(String(24),default='queued')
    environment_snapshot:Mapped[dict]=mapped_column(JSON)
    cases:Mapped[list]=mapped_column(JSON)
    case_hashes:Mapped[dict]=mapped_column(JSON)
    timeout_minutes:Mapped[int]=mapped_column(default=1440)
    retries:Mapped[int]=mapped_column(default=0)
    started_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    deadline:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    finished_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    cancel_requested:Mapped[bool]=mapped_column(default=False)
    cancel_requested_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    launch_attempted_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    remote_identity:Mapped[dict]=mapped_column(JSON,default=dict)
    result:Mapped[dict]=mapped_column(JSON,default=dict)
    error:Mapped[str]=mapped_column(Text,default='')
    __table_args__=(
        UniqueConstraint('run_id','module',name='uq_functional_child_module'),
        UniqueConstraint('run_id','position',name='uq_functional_child_position'),
        CheckConstraint('position >= 0',name='ck_functional_child_position'),
        CheckConstraint('timeout_minutes BETWEEN 1 AND 1440',name='ck_functional_child_timeout'),
        CheckConstraint('retries BETWEEN 0 AND 5',name='ck_functional_child_retries'),
    )


class FunctionalPreflight(Record,Base):
    __tablename__='functional_preflights'
    creator_id:Mapped[str]=mapped_column(ForeignKey('users.id'))
    token_hash:Mapped[str]=mapped_column(String(64),unique=True)
    request_digest:Mapped[str]=mapped_column(String(64))
    source_digest:Mapped[str]=mapped_column(String(64))
    expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    checks:Mapped[list]=mapped_column(JSON,default=list)
    required_confirmations:Mapped[list]=mapped_column(JSON,default=list)
    can_start:Mapped[bool]=mapped_column(default=False)
    consumed_by:Mapped[str|None]=mapped_column(ForeignKey('functional_runs.id'),nullable=True)


class FunctionalEvent(Record,Base):
    __tablename__='functional_events'
    child_id:Mapped[str]=mapped_column(ForeignKey('functional_module_runs.id'))
    seq:Mapped[int]=mapped_column()
    record:Mapped[dict]=mapped_column(JSON)
    __table_args__=(UniqueConstraint('child_id','seq',name='uq_functional_event_seq'),
                   CheckConstraint('seq > 0',name='ck_functional_event_seq'))


class FunctionalResource(Record,Base):
    __tablename__='functional_resources'
    child_id:Mapped[str]=mapped_column(ForeignKey('functional_module_runs.id'))
    resource_id:Mapped[str]=mapped_column(String(128))
    kind:Mapped[str]=mapped_column(String(80))
    cluster:Mapped[str]=mapped_column(String(255))
    host:Mapped[str|None]=mapped_column(String(255),nullable=True)
    user:Mapped[str|None]=mapped_column(String(120),nullable=True)
    name:Mapped[str|None]=mapped_column(Text,nullable=True)
    path:Mapped[str|None]=mapped_column(Text,nullable=True)
    port:Mapped[int|None]=mapped_column(nullable=True)
    owned:Mapped[bool]=mapped_column(default=False)
    phase:Mapped[str]=mapped_column(String(16),default='intent')
    remote_identity:Mapped[dict]=mapped_column(JSON,default=dict)
    __table_args__=(UniqueConstraint('child_id','resource_id',name='uq_functional_resource'),
                   CheckConstraint("phase IN ('intent','active','retained','removed','unknown')",name='ck_functional_resource_phase'))


# Persisted source inputs are immutable; lifecycle/result columns remain writable.
@event.listens_for(FunctionalRun, 'before_update')
def immutable_parent_snapshot(mapper, connection, row):
    state = inspect(row)
    if state.attrs.version.history.has_changes() or (row.version == 2 and any(
            state.attrs[name].history.has_changes() for name in (
                'snapshot', 'request_digest', 'idempotency_key', 'creator_id', 'cluster_id', 'machine_id'))):
        raise ValueError('functional submission snapshot is immutable')


@event.listens_for(FunctionalModuleRun, 'before_update')
def immutable_child_snapshot(mapper, connection, row):
    if any(inspect(row).attrs[name].history.has_changes() for name in (
            'run_id', 'module', 'position', 'environment_snapshot', 'cases', 'case_hashes', 'timeout_minutes', 'retries')):
        raise ValueError('functional module snapshot is immutable')
