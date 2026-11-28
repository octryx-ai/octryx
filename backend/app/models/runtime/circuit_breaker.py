import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class CircuitBreakerState(Base):
    __tablename__ = "circuit_breaker_states"

    connector_name = Column(String(100), primary_key=True)
    state = Column(String(32), nullable=False, default="closed", index=True)
    failure_count = Column(Integer, nullable=False, default=0)
    next_retry_at = Column(DateTime, nullable=True, index=True)
    last_error = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False, index=True)


class FailedTaskRun(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"task_id": "tasks"}
    __tablename__ = "failed_task_runs"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False, index=True)
    task_run_id = Column(String(36), ForeignKey("task_runs.id"), nullable=False, index=True)
    retry_count = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    next_retry_at = Column(DateTime, nullable=True, index=True)
    status = Column(String(32), nullable=False, default="pending_retry", index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False, index=True)
