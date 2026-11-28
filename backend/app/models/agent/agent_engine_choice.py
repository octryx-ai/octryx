"""A person's own choice of coding engine (Claude Code or Codex). One row per user, none means the Workspace default; it
counts only where the Workspace allows the engine."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, String

from ...db import Base
from ...time_utils import utc_now


class UserAgentEngine(Base):
    __tablename__ = "user_agent_engines"

    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    engine = Column(String(20), nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
