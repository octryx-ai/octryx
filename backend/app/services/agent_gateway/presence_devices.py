"""Presence per person and device: the device key, the read-model collapse, retention and removal."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentPresence, AuditLog, OAuthGrant
from ...time_utils import utc_now
from .identity import GatewayIdentity

logger = logging.getLogger(__name__)

PRESENCE_RETENTION = timedelta(days=7)
REMOVE_AUDIT_ACTION = "agent_gateway.presence.removed"


def _key(user_id: str, identity: str) -> str:
    return hashlib.sha256(f"{user_id}|{identity}".encode()).hexdigest()[:32]


async def device_key_for(db: AsyncSession, identity: GatewayIdentity) -> str:
    grant = await db.get(OAuthGrant, identity.grant_id) if identity.grant_id else None
    if grant is not None and grant.device_id:
        return _key(identity.user.id, f"device:{grant.device_id}")
    if identity.oauth_client_id:
        return _key(identity.user.id, f"client:{identity.oauth_client_id}")
    return _key(identity.user.id, f"grant:{identity.grant_id}")


async def registered_device_id(db: AsyncSession, identity: GatewayIdentity) -> str | None:
    grant = await db.get(OAuthGrant, identity.grant_id) if identity.grant_id else None
    return grant.device_id if grant is not None and grant.device_id else None


async def device_names(db: AsyncSession, device_ids: Iterable[str | None]) -> dict[str, str]:
    from ...models.security.device import UserDevice

    wanted = sorted({device_id for device_id in device_ids if device_id})
    if not wanted:
        return {}
    rows = await db.execute(select(UserDevice.id, UserDevice.name).where(UserDevice.id.in_(wanted)))
    return {device_id: name for device_id, name in rows.all()}


def entry_id(row: AgentPresence) -> str:
    return str(row.device_key)


def retained(now: datetime) -> Any:
    cutoff = now - PRESENCE_RETENTION
    # Both branches are NULL-free, so NOT(retained) in the sweep is never NULL (SQL three-valued logic).
    return or_(
        and_(AgentPresence.stopped_at.is_not(None), AgentPresence.stopped_at >= cutoff),
        and_(AgentPresence.stopped_at.is_(None), AgentPresence.last_seen_at >= cutoff),
    )


def collapse_entries(rows: Iterable[Sequence[Any]]) -> list[tuple[Sequence[Any], int]]:
    shown: dict[str, Sequence[Any]] = {}
    running: dict[str, int] = {}
    for result in rows:
        row = result[0]
        key = entry_id(row)
        if key not in shown or (shown[key][0].stopped_at is not None and row.stopped_at is None):
            shown[key] = result  # a running session is shown before a stopped one; order stays by first sighting
        running[key] = running.get(key, 0) + (1 if row.stopped_at is None else 0)
    return [(result, running[key]) for key, result in shown.items()]


async def expire_presence(db: AsyncSession, *, now: datetime | None = None) -> int:
    now = now or utc_now()
    result = await db.execute(delete(AgentPresence).where(not_(retained(now))))
    count = int(result.rowcount or 0)
    await db.commit()
    if count:  # a system sweep: logged, not a per-person audit entry (audit rows need an actor)
        logger.info("agent_presence.expired deleted=%s retention_days=%s", count, PRESENCE_RETENTION.days)
    return count


async def remove_presence_entry(
    db: AsyncSession, *, project_id: str, entry: str, actor_id: str, may_remove_others: bool
) -> int:
    statement = select(AgentPresence).where(
        AgentPresence.project_id == project_id,
        AgentPresence.device_key == entry,
    )
    if not may_remove_others:
        statement = statement.where(AgentPresence.user_id == actor_id)
    rows = list((await db.execute(statement)).scalars().all())
    if not rows:
        return 0
    owner_id = rows[0].user_id
    for row in rows:
        await db.delete(row)
    db.add(AuditLog(
        user_id=actor_id,
        action=REMOVE_AUDIT_ACTION,
        resource_type="agent_presence",
        resource_id=entry,
        project_id=project_id,
        details={"workspace_id": project_id, "owner_user_id": owner_id, "sessions": len(rows),
                 "running_sessions": sum(1 for row in rows if row.stopped_at is None),
                 "by_other": owner_id != actor_id},
    ))
    await db.flush()
    return len(rows)


__all__ = [
    "PRESENCE_RETENTION",
    "REMOVE_AUDIT_ACTION",
    "collapse_entries",
    "device_names",
    "device_key_for",
    "entry_id",
    "expire_presence",
    "registered_device_id",
    "remove_presence_entry",
    "retained",
]
