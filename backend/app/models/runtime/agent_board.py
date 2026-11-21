"""The agent message board of the agent coordination board.

``agent_board_message`` is append-only: questions, answers, infos, conflicts, handoff requests and decision
requests between agents and people of one Workspace. An admin redaction blanks ``body`` and ``options`` and
keeps the row as a tombstone (``redacted_at``/``redacted_by``). A ``decision`` answers one
``decision_request`` (its ``reply_to``); the partial unique index ``uq_agent_board_one_decision`` keeps it to
exactly one, so two people deciding at once have one winner. ``agent_board_ack`` records who has read a
message: a user, or an agent identity by its hash.
"""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text

from ...db import Base
from ...time_utils import utc_now


class AgentBoardMessage(Base):
    __tablename__ = "agent_board_message"
    __table_args__ = (
        Index(
            "uq_agent_board_one_decision",
            "reply_to",
            unique=True,
            postgresql_where=text("kind = 'decision'"),
            sqlite_where=text("kind = 'decision'"),
        ),
        Index("ix_agent_board_message_project_created", "project_id", "created_at"),
        Index("ix_agent_board_message_reply_to", "reply_to"),
        Index("ix_agent_board_message_to_user", "to_user_id"),
        Index("ix_agent_board_message_to_agent", "to_agent_hash"),
        Index(
            "uq_agent_board_auto_handoff",
            "claim_id",
            unique=True,
            postgresql_where=text("author_type = 'system'"),
            sqlite_where=text("author_type = 'system'"),
        ),
    )

    id = Column(String(36), primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    work_item_id = Column(String(36), ForeignKey("work_items.id", ondelete="CASCADE"), nullable=True)
    reply_to = Column(String(36), ForeignKey("agent_board_message.id", ondelete="CASCADE"), nullable=True)
    author_type = Column(String(10), nullable=False)
    author_user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    author_agent_hash = Column(String(24), nullable=True)
    on_behalf_of_user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    kind = Column(String(20), nullable=False)
    to_user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    to_agent_hash = Column(String(24), nullable=True)
    to_role = Column(String(20), nullable=True)
    body = Column(Text, nullable=False, default="")
    options = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    redacted_at = Column(DateTime, nullable=True)
    redacted_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # An automatic handoff request names the claim it is about (one per claim, ``uq_agent_board_auto_handoff``).
    # A plain reference (no FK): SQLite cannot add a constraint to the existing table in place.
    claim_id = Column(String(36), nullable=True)


class AgentBoardAck(Base):
    __tablename__ = "agent_board_ack"
    __table_args__ = (
        UniqueConstraint("message_id", "recipient_kind", "recipient_ref", name="uq_agent_board_ack_recipient"),
        Index("ix_agent_board_ack_recipient", "recipient_kind", "recipient_ref"),
    )

    id = Column(String(36), primary_key=True)
    message_id = Column(String(36), ForeignKey("agent_board_message.id", ondelete="CASCADE"), nullable=False)
    recipient_kind = Column(String(10), nullable=False)  # user | agent
    recipient_ref = Column(String(36), nullable=False)  # user id, or the agent hash
    recipient_user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    acked_at = Column(DateTime, nullable=False, default=utc_now)


__all__ = ["AgentBoardAck", "AgentBoardMessage"]
