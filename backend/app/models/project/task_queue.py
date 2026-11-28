import json
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now
from ..json_text import safe_json_dict


def uuid_pk():
    return str(uuid.uuid4())


class TaskQueueEntry(WorkspaceBound, Base):
    __workspace_owners__ = {"task_run_id": "task_runs"}
    __tablename__ = "task_queue_entries"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    task_run_id = Column(String(36), ForeignKey("task_runs.id"), nullable=False, unique=True, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    task_type = Column(String(50), nullable=False, default="scheduled_task", index=True)
    payload_json = Column(Text, default="{}")
    priority = Column(Integer, nullable=False, default=5, index=True)
    required_domain = Column(String(50), nullable=True, index=True)
    required_worker_id = Column(String(36), ForeignKey("agent_workers.id"), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    assigned_to = Column(String(36), ForeignKey("agent_workers.id"), nullable=True, index=True)
    assigned_at = Column(DateTime, nullable=True, index=True)
    queued_at = Column(DateTime, default=utc_now, index=True)
    started_at = Column(DateTime, nullable=True, index=True)
    last_heartbeat = Column(DateTime, nullable=True, index=True)
    completed_at = Column(DateTime, nullable=True, index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    next_retry_at = Column(DateTime, nullable=True, index=True)
    last_error = Column(Text, nullable=True)
    source_event_id = Column(String(36), nullable=True, index=True)
    result_session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True, index=True)
    expires_at = Column(DateTime, nullable=True, index=True)
    timeout_minutes = Column(Integer, nullable=True)
    estimated_wait_seconds = Column(Integer, nullable=False, default=0)
    queue_backend = Column(String(20), nullable=False, default="database")

    task_run = relationship("TaskRun", back_populates="queue_entry")
    project = relationship("Project")
    required_worker = relationship("AgentWorker", foreign_keys=[required_worker_id])
    assigned_worker = relationship("AgentWorker", foreign_keys=[assigned_to])
    result_session = relationship("Session", foreign_keys=[result_session_id])

    @property
    def payload(self) -> dict:
        return safe_json_dict(self.payload_json)

    @payload.setter
    def payload(self, value: dict):
        self.payload_json = json.dumps(value or {})
