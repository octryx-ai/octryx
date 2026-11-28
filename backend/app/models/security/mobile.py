"""Octryx Mobile: a user's paired phones and the one-time pairings that create them."""

from __future__ import annotations

import secrets

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text

from ...db import Base
from ...time_utils import utc_now

PAIRING_PENDING = "pending"  # created, not scanned yet
PAIRING_SCANNED = "scanned"  # a phone scanned it; the Mac must confirm the number
PAIRING_CONFIRMED = "confirmed"  # the Mac confirmed; the phone may claim
PAIRING_CLAIMED = "claimed"  # a mobile device exists
PAIRING_DENIED = "denied"  # the Mac said no
PAIRING_STATES = (PAIRING_PENDING, PAIRING_SCANNED, PAIRING_CONFIRMED, PAIRING_CLAIMED, PAIRING_DENIED)

MOBILE_ACTIVE = "active"
MOBILE_REVOKED = "revoked"


def pairing_pk() -> str:
    return f"mpr_{secrets.token_hex(8)}"


def mobile_device_pk() -> str:
    return f"mob_{secrets.token_hex(8)}"


class MobilePairing(Base):
    __tablename__ = "mobile_pairings"
    __table_args__ = (
        Index("ix_mobile_pairings_user_id", "user_id"),
        Index("ux_mobile_pairings_code_hash", "code_hash", unique=True),
        Index("ux_mobile_pairings_claim_hash", "claim_hash", unique=True),
    )

    id = Column(String(40), primary_key=True, default=pairing_pk)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    # The octryx-claude login that created the pairing; the phone lives only as long as that login is not revoked.
    grant_id = Column(String(36), nullable=True)
    code_hash = Column(String(64), nullable=False)
    state = Column(String(20), nullable=False, default=PAIRING_PENDING)
    expires_at = Column(DateTime, nullable=False)
    match_number = Column(String(2), nullable=True)
    scan_secret_hash = Column(String(64), nullable=True)
    phone_label = Column(String(80), nullable=True)
    scanned_at = Column(DateTime, nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    claim_hash = Column(String(64), nullable=True)
    claim_expires_at = Column(DateTime, nullable=True)
    claimed_at = Column(DateTime, nullable=True)
    mobile_device_id = Column(String(40), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class MobileDevice(Base):
    __tablename__ = "mobile_devices"
    __table_args__ = (
        Index("ix_mobile_devices_owner_user_id", "owner_user_id"),
        Index("ix_mobile_devices_owner_status", "owner_user_id", "status"),
        Index("ux_mobile_devices_secret_hash", "secret_hash", unique=True),
    )

    id = Column(String(40), primary_key=True, default=mobile_device_pk)
    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    grant_id = Column(String(36), nullable=True)
    name = Column(String(80), nullable=False)
    secret_hash = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default=MOBILE_ACTIVE)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    last_seen_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    revoke_reason = Column(String(200), nullable=True)


class MobilePushSubscription(Base):
    """The phone's Web Push subscription: where to send, which kinds it wants, what it was told already."""

    __tablename__ = "mobile_push_subscriptions"
    __table_args__ = (Index("ux_mobile_push_subscriptions_device", "mobile_device_id", unique=True),)

    id = Column(String(40), primary_key=True, default=lambda: f"mps_{secrets.token_hex(8)}")
    mobile_device_id = Column(String(40), ForeignKey("mobile_devices.id", ondelete="CASCADE"), nullable=False)
    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    endpoint = Column(Text, nullable=False)
    p256dh = Column(String(200), nullable=False)
    auth = Column(String(100), nullable=False)
    rules = Column(JSON, nullable=False, default=dict)
    notified = Column(JSON, nullable=True)
    failures = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    last_sent_at = Column(DateTime, nullable=True)


__all__ = [
    "MobilePushSubscription",
    "MOBILE_ACTIVE",
    "MOBILE_REVOKED",
    "PAIRING_CLAIMED",
    "PAIRING_CONFIRMED",
    "PAIRING_DENIED",
    "PAIRING_PENDING",
    "PAIRING_SCANNED",
    "PAIRING_STATES",
    "MobileDevice",
    "MobilePairing",
]
