import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class SessionCollaborator(Base):
    __tablename__ = "session_collaborators"

    session_id = Column(String(36), ForeignKey("sessions.id"), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), primary_key=True)
    role = Column(String(20), nullable=False, default="observer", index=True)
    invited_by = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    joined_at = Column(DateTime, default=utc_now, index=True)

    session = relationship("Session")
    user = relationship("User", foreign_keys=[user_id])
    inviter = relationship("User", foreign_keys=[invited_by])


class SessionHandover(Base):
    __tablename__ = "session_handovers"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    from_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    to_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    reason = Column(Text, nullable=True)
    context_summary = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    resolved_at = Column(DateTime, nullable=True)

    session = relationship("Session")
    from_user = relationship("User", foreign_keys=[from_user_id])
    to_user = relationship("User", foreign_keys=[to_user_id])
