"""Presence and allowance of one governed coding-client session (agent coordination board).

One row per launcher session key (the UI shows one entry per person and device: ``device_key``),
created when ``octryx-claude`` registers the session at launch
(``POST /api/v1/agent-gateway/sessions/register``) for either profile:

- ``governed``: model traffic through the platform's LiteLLM data plane; presence without allowance;
- ``seat``: model traffic through the gateway to Anthropic with the user's **own** subscription login.
  The row then also holds the session-bound seat credential, **as a SHA-256 hash only**, its expiry
  and the OAuth grant that registered it. The allowance fields are written from the upstream
  ``anthropic-ratelimit-unified-*`` response headers of the session's own seat calls.

The subscription token itself is never stored anywhere; it only travels through the seat route.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, String, Text

from ...db import Base
from ...time_utils import utc_now


class AgentPresence(Base):
    __tablename__ = "agent_presence"
    __table_args__ = (
        Index("ix_agent_presence_project_last_seen", "project_id", "last_seen_at"),
        Index("ix_agent_presence_seat_credential_hash", "seat_credential_hash", unique=True),
        Index("ix_agent_presence_project_device", "project_id", "device_key"),
    )

    id = Column(String(36), primary_key=True)
    session_key = Column(String(36), nullable=False, unique=True)
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    profile = Column(String(20), nullable=False)
    client = Column(String(40), nullable=False)
    client_version = Column(String(40), nullable=True)
    # One presence entry per person and device (``agent_gateway.presence_devices``), set when the session registers.
    device_key = Column(String(32), nullable=False)
    # The registered device (user_devices.id) when the login is a device grant; no FK, history survives revoke.
    device_id = Column(String(36), nullable=True)
    work_item_key = Column(String(120), nullable=True)
    branch = Column(String(200), nullable=True)
    model = Column(String(100), nullable=True)
    state = Column(String(20), nullable=False, default="active")
    five_hour_pct = Column(Float, nullable=True)
    five_hour_resets_at = Column(DateTime, nullable=True)
    seven_day_pct = Column(Float, nullable=True)
    seven_day_resets_at = Column(DateTime, nullable=True)
    allowance_status = Column(String(32), nullable=True)
    allowance_updated_at = Column(DateTime, nullable=True)
    seat_credential_hash = Column(String(64), nullable=True)
    seat_credential_expires_at = Column(DateTime, nullable=True)
    # Freeze 3c: when the session's use first reached the handoff trigger in the current crossing (cleared below it).
    handoff_crossing_at = Column(DateTime, nullable=True)
    # Freeze 3c "Hand over now": an admin asked this session to hand over (cleared by the session's next handoff).
    handoff_requested_at = Column(DateTime, nullable=True)
    seat_grant_id = Column(String(36), nullable=True)
    seat_oauth_client_id = Column(String(64), nullable=True)
    registered_at = Column(DateTime, nullable=False, default=utc_now)
    last_seen_at = Column(DateTime, nullable=False, default=utc_now)
    stopped_at = Column(DateTime, nullable=True)
    # Octryx Mobile: what the session is doing for the person's phone. ``activity`` is
    # ``working`` (a tool runs), ``approval`` (Claude Code asks the person) or ``waiting`` (the turn ended);
    # ``title`` is the first prompt's opening, ``last_text`` the last answer (redacted like the session digest).
    activity = Column(String(20), nullable=True)
    activity_at = Column(DateTime, nullable=True)
    title = Column(String(200), nullable=True)
    last_text = Column(Text, nullable=True)
    # The launcher's heartbeat (phone list only). Separate from ``last_seen_at`` on purpose: an idle open terminal
    # must neither renew work-item claims nor look alive to auto-takeover.
    heartbeat_at = Column(DateTime, nullable=True)


__all__ = ["AgentPresence"]
