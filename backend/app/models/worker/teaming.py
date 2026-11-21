import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship, validates

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (Index("ix_teams_created_by", "created_by"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(160), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    avatar_url = Column(String(500), nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=utc_now, index=True)

    creator = relationship("User", foreign_keys=[created_by])


class TeamMember(Base):
    __tablename__ = "team_members"

    team_id = Column(String(36), ForeignKey("teams.id"), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), primary_key=True)
    role = Column(String(30), nullable=False, default="member")
    added_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)

    team = relationship("Team")
    user = relationship("User", foreign_keys=[user_id])
    added_by_user = relationship("User", foreign_keys=[added_by])


class TeamProject(Base):
    __tablename__ = "team_projects"

    team_id = Column(String(36), ForeignKey("teams.id"), primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id"), primary_key=True)
    role = Column(String(30), nullable=False, default="member")
    granted_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)

    team = relationship("Team")
    project = relationship("Project")
    granted_by_user = relationship("User", foreign_keys=[granted_by])


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read_created", "user_id", "is_read", "created_at"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String(80), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=True)
    link = Column(String(500), nullable=True)
    is_read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utc_now, index=True)
    read_at = Column(DateTime, nullable=True)

    user = relationship("User")

    @validates("title", "body")
    def _unfenced(self, _key, value):
        """A notification is read by a person: no fence marker from a fenced read reaches it (fences belong only at a
        model's input). Every creator (team notifications, the agent board, action-needed) passes here."""
        from ...services.content_security.knowledge_fence import unfence_text

        return unfence_text(value)


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    user_id = Column(String(36), ForeignKey("users.id"), primary_key=True)
    in_app_enabled = Column(Boolean, nullable=False, default=True)
    email_enabled = Column(Boolean, nullable=False, default=False)
    slack_enabled = Column(Boolean, nullable=False, default=False)
    teams_enabled = Column(Boolean, nullable=False, default=False)
    # The companion's quiet hours: {enabled, start "HH:MM", end "HH:MM", timezone}; None = none set.
    quiet_hours = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    user = relationship("User")
