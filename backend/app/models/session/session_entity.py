import uuid

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Index, Integer, String

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class SessionEntity(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"session_id": "sessions"}
    __tablename__ = "session_entities"
    __table_args__ = (
        Index("ix_session_entities_session_relevance", "session_id", "relevance_score"),
        Index("ix_session_entities_unique", "session_id", "entity_type", "entity_id", unique=True),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    entity_type = Column(String(80), nullable=False, index=True)
    entity_id = Column(String(255), nullable=False)
    label = Column(String(255), nullable=False)
    state_json = Column(JSON, default=dict)
    first_seen_message_id = Column(String(36), ForeignKey("messages.id"), nullable=True, index=True)
    last_updated_message_id = Column(String(36), ForeignKey("messages.id"), nullable=True, index=True)
    relevance_score = Column(Float, nullable=False, default=1.0)
    times_seen = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)
