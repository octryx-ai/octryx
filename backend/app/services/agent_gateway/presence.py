"""Presence of governed coding-client sessions: registration, liveness, allowance, listing."""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentPresence, AuditLog, Session, User, WorkItem
from ...time_utils import utc_now
from ..agent_board.automation import request_handoffs_for_presence
from ..agent_board.claims import renew_gateway_claims
from ..content_routing.client_conversation import presence_sensitivity
from .allowance import Allowance
from .identity import GatewayIdentity
from .presence_devices import collapse_entries, device_key_for, device_names, entry_id, registered_device_id, retained
from .seat_credential import PROFILE_SEAT, PROFILES, credential_lifetime, mint_credential

logger = logging.getLogger(__name__)

STATE_ACTIVE = "active"
STATE_IDLE = "idle"
STATE_STOPPED = "stopped"
STATE_LIMIT_REACHED = "limit_reached"
IDLE_AFTER = timedelta(minutes=10)
TOUCH_EVERY = timedelta(seconds=15)
LIST_LIMIT = 200
LIST_SCAN_LIMIT = 2000  # session rows read to build the entries (retention already bounds them to seven days)
REGISTER_AUDIT_ACTION = "agent_gateway.session.registered"

REASON_PROFILE_INVALID = "profile_invalid"
REASON_REGISTRATION_INVALID = "registration_invalid"
REASON_ALREADY_REGISTERED = "session_already_registered"

_NARROW = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@+-]{0,199}$")
_LIMITS = {"branch": 200, "client": 40, "client_version": 40}


def session_key_hash(session_key: str) -> str:
    return hashlib.sha256(session_key.encode("utf-8")).hexdigest()[:24]


def _optional_field(body: Mapping[str, Any], name: str) -> str | None | bool:
    value = body.get(name)
    if value is None or value == "":
        return None
    if type(value) is not str or len(value) > _LIMITS[name] or not _NARROW.match(value):
        return False
    return value


async def _find(db: AsyncSession, session_key: str) -> AgentPresence | None:
    statement = select(AgentPresence).where(AgentPresence.session_key == session_key)
    return (await db.execute(statement)).scalar_one_or_none()


async def register_session(
    db: AsyncSession, *, identity: GatewayIdentity, session: Session, body: Mapping[str, Any]
) -> dict[str, Any] | str:
    profile = body.get("profile")
    if profile not in PROFILES:
        return REASON_PROFILE_INVALID
    fields = {name: _optional_field(body, name) for name in _LIMITS}
    if any(value is False for value in fields.values()):
        return REASON_REGISTRATION_INVALID
    if await _find(db, identity.session_key) is not None:
        return REASON_ALREADY_REGISTERED
    now = utc_now()
    row = AgentPresence(
        id=str(uuid.uuid4()),
        session_key=identity.session_key,
        session_id=session.id,
        user_id=identity.user.id,
        project_id=identity.workspace_id,
        profile=profile,
        client=fields["client"] or "octryx-claude",
        client_version=fields["client_version"],
        device_key=await device_key_for(db, identity),
        device_id=await registered_device_id(db, identity),
        work_item_key=identity.work_item_key or None,
        branch=fields["branch"],
        state=STATE_ACTIVE,
        registered_at=now,
        last_seen_at=now,
    )
    answer: dict[str, Any] = {"state": "registered", "profile": profile}
    if profile == PROFILE_SEAT:
        credential, hashed = mint_credential()
        row.seat_credential_hash = hashed
        row.seat_credential_expires_at = now + credential_lifetime()
        row.seat_grant_id = identity.grant_id
        row.seat_oauth_client_id = identity.oauth_client_id[:64] or None
        answer.update(
            {"seat_credential": credential, "credential_expires_at": row.seat_credential_expires_at.isoformat() + "Z"}
        )
    db.add(row)
    metadata = dict(session.metadata_ or {})
    metadata["gateway_profile"] = profile
    session.metadata_ = metadata
    db.add(
        AuditLog(
            user_id=identity.user.id,
            action=REGISTER_AUDIT_ACTION,
            resource_type="agent_presence",
            resource_id=row.id,
            project_id=row.project_id,
            details={"profile": profile, "client": row.client, "client_version": row.client_version,
                     "workspace_id": identity.workspace_id},
        )
    )
    await db.flush()
    return answer


async def touch_presence(db: AsyncSession, session_key: str, *, model: str | None = None) -> None:
    row = await _find(db, session_key)
    if row is None or row.stopped_at is not None:
        return
    now = utc_now()
    changed_model = bool(model) and row.model != model[:100]
    if changed_model:
        row.model = model[:100]
    if changed_model or row.last_seen_at is None or now - row.last_seen_at >= TOUCH_EVERY:
        row.last_seen_at = now
        await renew_gateway_claims(db, session_key_hash(session_key), now)
        await db.flush()


async def record_allowance(db: AsyncSession, session_key: str, allowance: Allowance,
                           engine: str = "claude_code") -> None:
    if not allowance.observed:
        return
    row = await _find(db, session_key)
    if row is None or row.stopped_at is not None:
        return
    for name in ("five_hour_pct", "five_hour_resets_at", "seven_day_pct", "seven_day_resets_at"):
        value = getattr(allowance, name)
        if value is not None:
            setattr(row, name, value)
    if allowance.status is not None:
        row.allowance_status = allowance.status
    stored = Allowance(row.five_hour_pct, row.five_hour_resets_at, row.seven_day_pct, row.seven_day_resets_at,
                       row.allowance_status)
    row.state = STATE_LIMIT_REACHED if stored.limit_reached else STATE_ACTIVE
    row.allowance_updated_at = row.last_seen_at = utc_now()
    from ..observability.seat_allowance_metrics import observe  # noqa: PLC0415

    observe(engine, stored, at=row.allowance_updated_at)
    await db.flush()
    # At or near the limit while holding claims: one automatic handoff request per claim. It runs in a
    # savepoint and never fails the seat call that reported the allowance.
    try:
        async with db.begin_nested():
            await request_handoffs_for_presence(db, row, session_key_hash(session_key))
    except Exception:  # noqa: BLE001 - the model call must not depend on the board
        logger.warning("Automatic handoff request failed for one session; the seat call continues", exc_info=True)


async def stop_presence(db: AsyncSession, session_key: str) -> None:
    row = await _find(db, session_key)
    if row is None:
        return
    row.state = STATE_STOPPED
    row.stopped_at = row.stopped_at or utc_now()
    row.seat_credential_hash = None
    row.seat_credential_expires_at = None
    row.last_text = None  # Octryx Mobile: the phone's copy of the last answer ends with the session
    await db.flush()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value is not None else None


def displayed_state(row: AgentPresence, now: datetime) -> str:
    if row.state == STATE_ACTIVE and row.last_seen_at is not None and now - row.last_seen_at >= IDLE_AFTER:
        return STATE_IDLE
    return row.state


async def _work_items(db: AsyncSession, project_id: str, keys: set[str]) -> dict[str, dict[str, str]]:
    if not keys:
        return {}
    rows = (
        await db.execute(
            select(WorkItem.id, WorkItem.source_key, WorkItem.title).where(
                WorkItem.project_id == project_id,
                or_(WorkItem.source_key.in_(sorted(keys)), WorkItem.id.in_(sorted(keys))),
            )
        )
    ).all()
    found: dict[str, dict[str, str]] = {}
    for item_id, key, title in rows:
        entry = {"id": item_id, "key": key, "title": title}
        found.setdefault(key, entry)
        found.setdefault(item_id, entry)
    return found


async def list_presence(db: AsyncSession, *, project_id: str, include_allowance: bool) -> dict[str, Any]:
    now = utc_now()
    entries = collapse_entries(
        (
            await db.execute(
                select(AgentPresence, User.display_name, User.username)
                .join(User, User.id == AgentPresence.user_id)
                .where(AgentPresence.project_id == project_id, retained(now))
                .order_by(AgentPresence.last_seen_at.desc())
                .limit(LIST_SCAN_LIMIT)
            )
        ).all()
    )[:LIST_LIMIT]
    rows = [result for result, _ in entries]
    running = {entry_id(result[0]): count for result, count in entries}
    items_by_key = await _work_items(db, project_id, {row.work_item_key for row, _, _ in rows if row.work_item_key})
    # The current conversation's sensitive categories and counts (never content), for the badge.
    sensitive = await presence_sensitivity(db, [row.session_id for row, _, _ in rows])
    names = await device_names(db, (row.device_id for row, _, _ in rows))
    items = []
    for row, display_name, username in rows:
        allowance = None
        if include_allowance and row.profile == PROFILE_SEAT:
            allowance = {
                "five_hour_pct": row.five_hour_pct,
                "five_hour_resets_at": _iso(row.five_hour_resets_at),
                "seven_day_pct": row.seven_day_pct,
                "seven_day_resets_at": _iso(row.seven_day_resets_at),
                "status": row.allowance_status,
            }
        items.append(
            {
                "id": entry_id(row),
                "session_key_hash": session_key_hash(row.session_key),
                "sessions": running[entry_id(row)],
                "user": {"id": row.user_id, "display_name": display_name or username},
                "client": row.client,
                "device": {"id": row.device_id, "name": names.get(row.device_id)} if row.device_id else None,
                "profile": row.profile,
                "state": displayed_state(row, now),
                "work_item": items_by_key.get(row.work_item_key) if row.work_item_key else None,
                "branch": row.branch,
                "model": row.model,
                "last_seen_at": _iso(row.last_seen_at),
                "allowance": allowance,
                "sensitive": sensitive.get(row.session_id) if row.session_id else None,
            }
        )
    return {"items": items}


__all__ = [
    "IDLE_AFTER",
    "REASON_ALREADY_REGISTERED",
    "REASON_PROFILE_INVALID",
    "REASON_REGISTRATION_INVALID",
    "STATE_ACTIVE",
    "STATE_IDLE",
    "STATE_LIMIT_REACHED",
    "STATE_STOPPED",
    "displayed_state",
    "list_presence",
    "record_allowance",
    "register_session",
    "session_key_hash",
    "stop_presence",
    "touch_presence",
]
