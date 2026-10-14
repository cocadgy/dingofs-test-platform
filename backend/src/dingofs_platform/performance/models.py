from datetime import datetime
from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, Index, text
from sqlalchemy.orm import Mapped, mapped_column
from dingofs_platform.db import Base,Record

ACTIVE=('queued','running','cancelling','unknown')


class PerformanceRun(Record,Base):
    __tablename__='performance_runs'
    creator_id: Mapped[str]=mapped_column(String(36))
    machine_id: Mapped[str]=mapped_column(ForeignKey('machines.id'))
    name: Mapped[str]=mapped_column(String(120))
    state: Mapped[str]=mapped_column(String(24),default='queued')
    phase: Mapped[str]=mapped_column(String(160),default='等待执行')
    progress: Mapped[int]=mapped_column(default=0)
    snapshot: Mapped[dict]=mapped_column(JSON)
    log: Mapped[str]=mapped_column(Text,default='')
    error: Mapped[str]=mapped_column(Text,default='')
    reports: Mapped[dict]=mapped_column(JSON,default=dict)
    remote_root: Mapped[str | None]=mapped_column(Text,nullable=True)
    cancel_requested: Mapped[bool]=mapped_column(default=False)
    deadline: Mapped[datetime]=mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True),nullable=True)
    __table_args__=(Index('uq_performance_active_machine','machine_id',unique=True,
                         postgresql_where=text("state IN ('queued','running','cancelling','unknown')")),)
