import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class Approval(WorkspaceBound, Base):
    __workspace_owners__ = {"session_id": "sessions", "task_run_id": "task_runs"}
    __workspace_column__ = "workspace_id"
    __tablename__ = "approvals"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    task_run_id = Column(String(36), ForeignKey("task_runs.id"), nullable=True, index=True)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True, index=True)
    # The Workspace of a governance review (no session, no task run); NULL otherwise, and NULL
    # on a review whose Workspace could not be derived (then only a global admin sees it).
    workspace_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    requested_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    approved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    action = Column(String(200), nullable=False)
    status = Column(String(50), default="pending", index=True)
    # Why the approval was requested; kept as written. The decider's note goes to ``decision_note``.
    reason = Column(Text, nullable=True)
    decision_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    resolved_at = Column(DateTime, nullable=True)

    task_run = relationship("TaskRun")
    session = relationship("Session")
    requester = relationship("User", foreign_keys=[requested_by])
    approver = relationship("User", foreign_keys=[approved_by])
