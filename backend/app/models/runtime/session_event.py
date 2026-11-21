"""Session State Transition Event Log — WAL pattern for crash recovery."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


class SessionEvent(Base):
    """Append-only event log recording every meaningful session state transition.

    Acts as the Write-Ahead Log (WAL) for crash recovery. Each row captures
    a single atomic state change — the system of record is always this log.
    The current session state (status, run_status, etc.) is a derived snapshot
    maintained for query efficiency.
    """

    __tablename__ = "session_events"
    __table_args__ = (
        Index("ix_session_events_session_index", "session_id", "event_index"),
        Index("ix_session_events_session_type", "session_id", "event_type"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    event_type = Column(String(60), nullable=False, index=True)
    from_status = Column(String(40), nullable=True)
    to_status = Column(String(40), nullable=True)
    from_run_status = Column(String(30), nullable=True)
    to_run_status = Column(String(30), nullable=True)
    actor = Column(String(60), nullable=True)  # "worker", "user", "system", "scheduler"
    trigger = Column(String(60), nullable=True)
    remote_addr = Column(String(45), nullable=True)
    details = Column(JSON, default=dict)
    event_index = Column(String(20), nullable=True)  # monotonic counter per session, e.g. "000001"
    created_at = Column(DateTime, default=utc_now, index=True)

    session = relationship("Session")


__all__ = ["SessionEvent"]
