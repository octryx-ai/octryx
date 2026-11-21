"""Octryx Mobile "live": the Claude Code sessions running on a person's device and their messages.

- ``device_live_snapshots``: one row per device, the last list of running sessions the device reported
  (``services/devices/live``). Only the device's owner reads it.
- ``live_messages``: what the owner sent to one of those sessions (``out``) and what came back (``in``). An ``out``
  row is ``pending`` until the channel takes it to the device (``sent``), then ``delivered``, ``altered`` (the
  relay changed the text: not delivered as written) or ``failed``.
- ``live_attachments``: a picture attached to an ``out`` message, kept only until the device settled
  the message, then deleted; ``live_messages.attachment_count`` keeps how many there were.
"""

from __future__ import annotations

import secrets

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text

from ...db import Base
from ...time_utils import utc_now

LIVE_OUT = "out"
LIVE_IN = "in"


def live_message_pk() -> str:
    return f"lm_{secrets.token_hex(10)}"


class DeviceLiveSnapshot(Base):
    __tablename__ = "device_live_snapshots"

    device_id = Column(String(40), ForeignKey("user_devices.id", ondelete="CASCADE"), primary_key=True)
    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    sessions = Column(JSON, nullable=False, default=list)
    live = Column(String(5), nullable=False, default="on")
    reported_at = Column(DateTime, default=utc_now, nullable=False)


class LiveMessage(Base):
    __tablename__ = "live_messages"
    __table_args__ = (
        Index("ix_live_messages_owner_peer", "owner_user_id", "device_id", "peer", "created_at"),
        Index("ix_live_messages_device_state", "device_id", "state"),
    )

    id = Column(String(40), primary_key=True, default=live_message_pk)
    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    device_id = Column(String(40), ForeignKey("user_devices.id", ondelete="CASCADE"), nullable=False)
    peer = Column(String(300), nullable=False)
    direction = Column(String(3), nullable=False)
    name = Column(String(120), nullable=True)
    text = Column(Text, nullable=False)
    state = Column(String(20), nullable=False)
    reason = Column(String(60), nullable=True)
    attachment_count = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class LiveProgressEvent(Base):
    """What a listed session is doing: one short event, numbered per session."""

    __tablename__ = "live_progress_events"
    __table_args__ = (
        Index("ix_live_progress_events_session", "device_id", "peer", "seq"),
        Index("ix_live_progress_events_created", "device_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String(40), ForeignKey("user_devices.id", ondelete="CASCADE"), nullable=False)
    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    peer = Column(String(300), nullable=False)
    seq = Column(Integer, nullable=False)
    kind = Column(String(16), nullable=False)
    body = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False)


def live_attachment_pk() -> str:
    return f"la_{secrets.token_hex(10)}"


class LiveAttachment(Base):
    __tablename__ = "live_attachments"

    id = Column(String(40), primary_key=True, default=live_attachment_pk)
    message_id = Column(String(40), ForeignKey("live_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    media_type = Column(String(40), nullable=False)
    size = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    content = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)


__all__ = ["LIVE_IN", "LIVE_OUT", "DeviceLiveSnapshot", "LiveAttachment", "LiveMessage", "LiveProgressEvent",
           "live_attachment_pk", "live_message_pk"]
