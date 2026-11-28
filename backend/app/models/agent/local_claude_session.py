"""A Claude Code session outside octryx on one of the person's devices."""

from __future__ import annotations

import secrets

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text, UniqueConstraint

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def local_session_pk() -> str:
    return f"lcs_{secrets.token_hex(8)}"


class LocalClaudeSession(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"thread_session_id": "sessions"}
    __tablename__ = "local_claude_sessions"
    __table_args__ = (UniqueConstraint("device_id", "profile", "claude_session_id",
                                       name="uq_local_claude_sessions_device_profile_session"),)

    id = Column(String(40), primary_key=True, default=local_session_pk)
    device_id = Column(String(40), ForeignKey("user_devices.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    profile = Column(String(14), nullable=False)
    claude_session_id = Column(String(80), nullable=False)
    cwd = Column(String(500), nullable=False)
    title = Column(String(200), nullable=True)
    last_text = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=True)
    reported_at = Column(DateTime, nullable=False, default=utc_now)
    # The private-Workspace chat thread that took this session over (its turns run as device jobs), if any.
    thread_session_id = Column(String(36), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    # Whether the Mac lets the phone take this profile's sessions over (``profiles connect --allow-takeover``).
    takeover_allowed = Column(Boolean, nullable=False, default=False)


__all__ = ["LocalClaudeSession"]
