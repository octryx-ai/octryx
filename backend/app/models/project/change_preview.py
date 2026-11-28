import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class ChangePreview(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"session_id": "sessions", "approval_id": "approvals"}
    __tablename__ = "change_previews"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    task_run_id = Column(String(36), ForeignKey("task_runs.id"), nullable=True, index=True)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True, index=True)
    approval_id = Column(String(36), ForeignKey("approvals.id"), nullable=True, index=True)
    tool_name = Column(String(120), nullable=False, index=True)
    request_fingerprint = Column(String(64), nullable=True, index=True)
    preview_json = Column(Text, nullable=False)
    acknowledged_by = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    acknowledged_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    task_run = relationship("TaskRun")
    session = relationship("Session")
    approval = relationship("Approval")
    acknowledged_by_user = relationship("User", foreign_keys=[acknowledged_by])
