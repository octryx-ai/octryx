import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class ContextCheckpoint(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"session_id": "sessions"}
    __tablename__ = "context_checkpoints"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    checkpoint_name = Column(String(200), nullable=False, index=True)
    context_snapshot_json = Column(JSON, default=dict)
    status = Column(String(20), nullable=False, default="active", index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    released_at = Column(DateTime, nullable=True, index=True)
