"""A user's own octryx-claude device that can run chat requests (remote device sessions).

A device belongs to exactly one user. Only its owner can send work to it or answer its approvals; admins can
see, audit, pause and revoke it, never drive it. The device's background credential is an OAuth grant bound
to this row (``OAuthGrant.device_id``); revoking the device revokes the grant.
"""

from __future__ import annotations

import secrets

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text

from ...db import Base
from ...time_utils import utc_now

DEVICE_STATUS_ACTIVE = "active"
DEVICE_STATUS_REVOKED = "revoked"
# Six: a team's items run side by side on one Mac (four slots left the fourth
# item of a story waiting); the run's main-thread platform turns take none of them (``teamwork.slots``).
DEFAULT_MAX_PARALLEL_JOBS = 6


def device_pk() -> str:
    return f"dev_{secrets.token_hex(8)}"


class UserDevice(Base):
    __tablename__ = "user_devices"
    __table_args__ = (Index("ix_user_devices_owner_name", "owner_user_id", "name_key"),)

    id = Column(String(40), primary_key=True, default=device_pk)
    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(80), nullable=False)
    # Lower-cased name: names are unique per owner among devices that are not revoked.
    name_key = Column(String(80), nullable=False)
    os = Column(String(20), nullable=False)
    # Ed25519 public key (raw 32 bytes, base64url): the device signs the channel nonce with its private key.
    public_key = Column(Text, nullable=False)
    client_version = Column(String(40), nullable=True)
    service_kind = Column(String(40), nullable=True)
    # The folder allowlist as last reported by the device. The platform can only narrow it.
    folders = Column(JSON, nullable=False, default=list)
    profiles = Column(JSON, nullable=False, default=list)
    max_parallel_jobs = Column(Integer, nullable=False, default=DEFAULT_MAX_PARALLEL_JOBS)
    status = Column(String(20), nullable=False, default=DEVICE_STATUS_ACTIVE, index=True)
    paused = Column(Boolean, nullable=False, default=False)
    grant_id = Column(String(36), ForeignKey("oauth_grants.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    last_seen_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    revoke_reason = Column(String(200), nullable=True)


__all__ = [
    "DEFAULT_MAX_PARALLEL_JOBS",
    "DEVICE_STATUS_ACTIVE",
    "DEVICE_STATUS_REVOKED",
    "UserDevice",
    "device_pk",
]
