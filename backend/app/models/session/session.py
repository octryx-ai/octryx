import uuid

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
    select,
)
from sqlalchemy.orm import relationship, validates

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


# Who created a session. Every creator sets it explicitly; the chat sidebar lists
# ``chat`` and ``device_chat`` only, so machine sessions never leak in as empty "New thread" rows.
SESSION_ORIGINS = frozenset(
    {
        "chat",
        "device_chat",
        "model_gateway",
        "mcp",
        "work_item_analysis",
        "webhook",
        "channel",
        "control_plane_test",
        "scheduler",
        "worker",
        "flow",
        "sub_agent",
    }
)
CHAT_SIDEBAR_ORIGINS = ("chat", "device_chat")


class Session(WorkspaceBound, Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_user_project_last_activity", "user_id", "project_id", "last_activity_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    agent_type = Column(String(50), default="diagnosis")
    status = Column(String(50), default="active", index=True)
    metadata_ = Column("metadata", JSON, default=dict)
    run_status = Column(String(30), nullable=True, index=True)
    started_at = Column(DateTime, default=utc_now, index=True)
    ended_at = Column(DateTime, nullable=True)
    parent_session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True, index=True)
    sub_agent_depth = Column(Integer, default=0, nullable=False)
    recovery_policy = Column(String(20), default="manual_resume", nullable=False)  # auto_retry | manual_resume | fail
    # The platform process (``runtime_process_leases.id``) that last started a turn here.
    # A ``running`` session whose owner has no live lease is settled (runtime robustness).
    turn_owner_process_id = Column(String(36), nullable=True)
    origin = Column(String(40), nullable=False, default="chat", server_default="chat")
    # When a turn was last recorded: the sidebar orders and sections by it.
    last_activity_at = Column(DateTime, nullable=True, default=utc_now)

    user = relationship("User", back_populates="sessions")
    project = relationship("Project", back_populates="sessions")

    @validates("origin")
    def _validate_origin(self, _key: str, value: str) -> str:
        if value not in SESSION_ORIGINS:
            raise ValueError(f"Unknown session origin: {value!r}")
        return value

    messages = relationship("Message", back_populates="session", order_by="Message.created_at")
    access_grants = relationship("SessionAccess", back_populates="session", cascade="all, delete-orphan")


class Message(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"session_id": "sessions"}
    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    content = Column(Text)
    tool_calls = Column(JSON, nullable=True)
    tool_results = Column(JSON, nullable=True)
    model = Column(String(100), nullable=True)
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    cost = Column(Numeric(10, 6), default=0)
    idempotency_key = Column(String(100), nullable=True, index=True)
    # Who wrote a user message; the session's owner can change by a hand-over, the author never does.
    author_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)

    session = relationship("Session", back_populates="messages")
    feedbacks = relationship("MessageFeedback", back_populates="message")

    @validates("role", "content")
    def _assistant_text_unfenced(self, key, value):
        # Fence only at a model's input, never at an exit: a quoted fenced passage would show the markers to the person
        # and in every export.
        from ...services.content_security.knowledge_fence import unfence_text

        if key == "content":
            return unfence_text(value) if self.role == "assistant" else value
        if value == "assistant" and isinstance(self.content, str):
            self.content = unfence_text(self.content)
        return value


# A user message written without an explicit author is its session owner's at that moment (the platform's own
# continuation of a run, a held device prompt); the paths where another person writes name the author themselves.
def _default_author(_mapper, connection, target: Message) -> None:
    if target.role == "user" and target.author_user_id is None and target.session_id:
        target.author_user_id = connection.execute(
            select(Session.user_id).where(Session.id == target.session_id)).scalar_one_or_none()


event.listen(Message, "before_insert", _default_author)


class MessageFeedback(Base):
    __tablename__ = "message_feedbacks"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    message_id = Column(String(36), ForeignKey("messages.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    # 1 = positive (thumbs up), -1 = negative (thumbs down)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    message = relationship("Message", back_populates="feedbacks")
    user = relationship("User")


class SessionAccess(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"session_id": "sessions"}
    __tablename__ = "session_access"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_session_access_session_user"),
        Index("ix_session_access_session", "session_id"),
        Index("ix_session_access_user", "user_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    access_scope = Column(String(20), nullable=False, default="read")
    granted_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    granted_at = Column(DateTime, default=utc_now, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    metadata_ = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    session = relationship("Session", back_populates="access_grants")
    user = relationship("User", foreign_keys=[user_id])
    granted_by_user = relationship("User", foreign_keys=[granted_by])

