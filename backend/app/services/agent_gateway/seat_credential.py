"""The session-bound seat credential: stored only as its SHA-256 and re-checked on every call."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentPresence, User
from ...models.security.oauth_provider import OAuthGrant
from ...time_utils import utc_now
from ..data_access import as_viewer, bind_request_viewer
from ..data_access.machine_principal import integration_owner
from ..project import get_user_project_ids
from .contract import (
    HEADER_SESSION,
    HEADER_WORKSPACE,
    REASON_SESSION_HEADER_INVALID,
    REASON_USER_INACTIVE,
    REASON_WORKSPACE_NOT_AUTHORIZED,
    STATE_DENIED,
    STATE_NEEDS_CONFIGURATION,
    STATE_UNAUTHORIZED,
)
from .identity import GatewayIdentity, GatewayRefusal

HEADER_SEAT_CREDENTIAL = "x-octryx-seat-credential"
PROFILE_SEAT = "seat"
PROFILE_GOVERNED = "governed"
PROFILES = frozenset({PROFILE_SEAT, PROFILE_GOVERNED})
LIFETIME_ENV = "OCTRYX_SEAT_CREDENTIAL_HOURS"
DEFAULT_LIFETIME_HOURS = 12
MAX_LIFETIME_HOURS = 24
CREDENTIAL_BYTES = 32

REASON_SEAT_CREDENTIAL_MISSING = "seat_credential_missing"
REASON_SEAT_CREDENTIAL_INVALID = "seat_credential_invalid"
REASON_SEAT_SESSION_EXPIRED = "seat_session_expired"
REASON_SEAT_GRANT_REVOKED = "seat_grant_revoked"
EXPIRED_HINT = "The seat session ended. Start a new session: octryx-claude --profile seat"


def credential_lifetime(environ: Mapping[str, str] | None = None) -> timedelta:
    raw = str((os.environ if environ is None else environ).get(LIFETIME_ENV) or "").strip()
    hours = int(raw) if raw.isdigit() else DEFAULT_LIFETIME_HOURS
    return timedelta(hours=min(max(hours, 1), MAX_LIFETIME_HOURS))


def credential_hash(credential: str) -> str:
    return hashlib.sha256(credential.encode("utf-8")).hexdigest()


def mint_credential() -> tuple[str, str]:
    # Only the hash is ever stored.
    credential = secrets.token_urlsafe(CREDENTIAL_BYTES)
    return credential, credential_hash(credential)


def _session_key(headers: Mapping[str, str]) -> str:
    try:
        return str(uuid.UUID(str(headers.get(HEADER_SESSION) or "").strip()))
    except ValueError:
        return ""


def _expired(row: AgentPresence, now: datetime) -> bool:
    return row.stopped_at is not None or row.seat_credential_expires_at is None or row.seat_credential_expires_at <= now


async def _live_grant(db: AsyncSession, row: AgentPresence) -> OAuthGrant | None:
    grant = await db.get(OAuthGrant, row.seat_grant_id) if row.seat_grant_id else None
    if grant is None or grant.user_id != row.user_id:
        return None
    if grant.revoked_at is None:
        return grant
    # A device renewal revokes the old grant and issues a new one: the session follows the device's current grant.
    if not grant.device_id:
        return None
    from ...models import UserDevice  # noqa: PLC0415
    from ...models.security.device import DEVICE_STATUS_ACTIVE  # noqa: PLC0415

    device = await db.get(UserDevice, grant.device_id)
    if device is None or device.status != DEVICE_STATUS_ACTIVE or device.owner_user_id != row.user_id \
            or not device.grant_id or device.grant_id == grant.id:
        return None
    current = await db.get(OAuthGrant, device.grant_id)
    if current is None or current.revoked_at is not None or current.user_id != row.user_id \
            or current.device_id != device.id or current.client_id != grant.client_id:
        return None
    return current


async def resolve_seat_identity(db: AsyncSession, headers: Mapping[str, str]) -> GatewayIdentity | GatewayRefusal:
    credential = str(headers.get(HEADER_SEAT_CREDENTIAL) or "").strip()
    if not credential or len(credential) > 200:
        return GatewayRefusal(STATE_UNAUTHORIZED, REASON_SEAT_CREDENTIAL_MISSING)
    session_key = _session_key(headers)
    if not session_key:
        return GatewayRefusal(STATE_NEEDS_CONFIGURATION, REASON_SESSION_HEADER_INVALID)
    hashed = credential_hash(credential)
    owner = await integration_owner(db, AgentPresence, hashed, owner_column="user_id",
                                    key_column="seat_credential_hash")
    with as_viewer(owner.user_id):
        identity = await _seat_identity(db, headers, hashed, session_key)
    if isinstance(identity, GatewayIdentity):
        bind_request_viewer(owner.user_id)
    return identity


async def _seat_identity(db: AsyncSession, headers: Mapping[str, str], hashed: str,
                         session_key: str) -> GatewayIdentity | GatewayRefusal:
    row = (
        await db.execute(select(AgentPresence).where(AgentPresence.seat_credential_hash == hashed))
    ).scalar_one_or_none()
    if (
        row is None
        or row.profile != PROFILE_SEAT
        or not hmac.compare_digest(row.session_key, session_key)
    ):
        return GatewayRefusal(STATE_UNAUTHORIZED, REASON_SEAT_CREDENTIAL_INVALID)
    if _expired(row, utc_now()):
        return GatewayRefusal(STATE_UNAUTHORIZED, REASON_SEAT_SESSION_EXPIRED)
    workspace = str(headers.get(HEADER_WORKSPACE) or "").strip()
    if workspace and workspace != row.project_id:
        return GatewayRefusal(STATE_DENIED, REASON_WORKSPACE_NOT_AUTHORIZED)
    grant = await _live_grant(db, row)
    if grant is None:
        return GatewayRefusal(STATE_UNAUTHORIZED, REASON_SEAT_GRANT_REVOKED)
    user = await db.get(User, row.user_id)
    if user is None or not bool(getattr(user, "is_active", True)):
        return GatewayRefusal(STATE_UNAUTHORIZED, REASON_USER_INACTIVE)
    # The gateway's binding semantics (``oauth_provider/resource``): null or empty is unrestricted.
    bound = grant.project_ids
    if isinstance(bound, list) and bound and row.project_id not in bound:
        return GatewayRefusal(STATE_DENIED, REASON_WORKSPACE_NOT_AUTHORIZED)
    if row.project_id not in set(await get_user_project_ids(user.id, db)):
        return GatewayRefusal(STATE_DENIED, REASON_WORKSPACE_NOT_AUTHORIZED)
    return GatewayIdentity(
        user=user,
        grant_id=grant.id,
        oauth_client_id=str(row.seat_oauth_client_id or ""),
        workspace_id=row.project_id,
        session_key=row.session_key,
        work_item_key=str(row.work_item_key or ""),
    )


__all__ = [
    "EXPIRED_HINT",
    "HEADER_SEAT_CREDENTIAL",
    "PROFILES",
    "PROFILE_GOVERNED",
    "PROFILE_SEAT",
    "REASON_SEAT_CREDENTIAL_INVALID",
    "REASON_SEAT_CREDENTIAL_MISSING",
    "REASON_SEAT_GRANT_REVOKED",
    "REASON_SEAT_SESSION_EXPIRED",
    "credential_hash",
    "credential_lifetime",
    "mint_credential",
    "resolve_seat_identity",
]
