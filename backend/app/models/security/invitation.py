import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class UserInvitation(Base):
    __tablename__ = "user_invitations"
    __table_args__ = (
        Index("ix_user_invitations_email", "email"),
        Index("ix_user_invitations_expires_at", "expires_at"),
        Index("ix_user_invitations_accepted_at", "accepted_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    email = Column(String(255), nullable=False)
    invited_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    team_id = Column(String(36), ForeignKey("teams.id"), nullable=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)
    role = Column(String(30), nullable=False, default="member")
    token_hash = Column(String(128), nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    accepted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)
