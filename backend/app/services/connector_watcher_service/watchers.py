"""Listing, creating and updating connector watchers."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorWatcher, User
from ...services.secret import get_secret_value, set_secret_value
from ..connector_watcher_polling import UnsupportedPollingTriggerError, normalize_connector_watcher_polling_config
from ..connector_watcher_scope import WatcherScope, require_write_scope, scope_filter
from ..secure_work.jira_values import blank_to_none, object_value, string_list
from .common import WATCHER_MODES, _audit, _get_watcher, _retry_policy
from .serialize import serialize_connector_watcher


async def list_connector_watchers(
    db: AsyncSession,
    *,
    scope: WatcherScope,
    project_id: str | None = None,
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    """The watchers of ``scope`` (``connector_watcher_scope``); the caller has checked a named ``project_id``."""
    stmt = select(ConnectorWatcher).where(scope_filter(ConnectorWatcher.project_id, scope, project_id))
    if not include_inactive:
        stmt = stmt.where(ConnectorWatcher.is_active.is_(True))
    rows = (
        (await db.execute(stmt.order_by(ConnectorWatcher.connector_name.asc(), ConnectorWatcher.name.asc())))
        .scalars()
        .all()
    )
    return [serialize_connector_watcher(row) for row in rows]


async def create_connector_watcher(
    db: AsyncSession,
    *,
    current_user: User,
    scope: WatcherScope,
    payload: dict[str, Any],
) -> dict[str, Any]:
    normalized = await _normalized_watcher_payload(db, current_user, scope, payload, include_runtime_defaults=True)
    secret = blank_to_none(payload.get("webhook_secret"))
    watcher = ConnectorWatcher(**normalized, created_by=current_user.id, updated_by=current_user.id)
    db.add(watcher)
    await db.flush()
    if secret:
        entry = await set_secret_value(
            db,
            tool_name=f"connector_watcher:{watcher.id}",
            field_name="webhook_secret",
            project_id=watcher.project_id,
            value=secret,
        )
        watcher.secret_ref = entry.id
    db.add(_audit(current_user, "connector_watcher.created", watcher.id, {"connector_name": watcher.connector_name},
                  project_id=watcher.project_id))
    await db.flush()
    return serialize_connector_watcher(watcher)


async def update_connector_watcher(
    db: AsyncSession,
    *,
    watcher_id: str,
    current_user: User,
    scope: WatcherScope,
    payload: dict[str, Any],
) -> dict[str, Any]:
    watcher = await _get_watcher(db, watcher_id, scope=scope)
    normalized = await _normalized_watcher_payload(db, current_user, scope, payload, include_runtime_defaults=False)
    for key, value in normalized.items():
        setattr(watcher, key, value)
    watcher.updated_by = current_user.id
    secret = blank_to_none(payload.get("webhook_secret"))
    if secret:
        entry = await set_secret_value(
            db,
            tool_name=f"connector_watcher:{watcher.id}",
            field_name="webhook_secret",
            project_id=watcher.project_id,
            value=secret,
        )
        watcher.secret_ref = entry.id
    db.add(_audit(current_user, "connector_watcher.updated", watcher.id, {"connector_name": watcher.connector_name},
                  project_id=watcher.project_id))
    await db.flush()
    return serialize_connector_watcher(watcher)


async def _normalized_watcher_payload(
    db: AsyncSession,
    current_user: User,
    scope: WatcherScope,
    payload: dict[str, Any],
    *,
    include_runtime_defaults: bool,
) -> dict[str, Any]:
    project_id = blank_to_none(payload.get("project_id"))
    await require_write_scope(db, current_user, scope, project_id)
    name = str(payload.get("name") or "").strip()
    connector_name = str(payload.get("connector_name") or "").strip()
    if not name or not connector_name:
        raise HTTPException(status_code=422, detail="name and connector_name are required")
    mode = str(payload.get("mode") or "webhook").strip().lower()
    if mode not in WATCHER_MODES:
        raise HTTPException(status_code=422, detail="Unsupported watcher mode")
    polling = object_value(payload.get("polling")) or {"enabled": mode in {"polling", "hybrid"}}
    try:
        polling_config = normalize_connector_watcher_polling_config(polling, mode=mode)
    except UnsupportedPollingTriggerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    normalized = {
        "project_id": project_id,
        "connector_name": connector_name[:200],
        "connector_instance": str(payload.get("connector_instance") or "default").strip()[:220],
        "provider_type": str(payload.get("provider_type") or "generic").strip().lower()[:80],
        "name": name[:220],
        "description": blank_to_none(payload.get("description")),
        "mode": mode,
        "event_types_json": string_list(payload.get("event_types")),
        "scope_json": object_value(payload.get("scope")),
        "polling_json": polling_config,
        "webhook_json": object_value(payload.get("webhook")) or {"enabled": mode in {"webhook", "hybrid"}},
        "retry_policy_json": _retry_policy(payload.get("retry_policy")),
        "is_active": bool(payload.get("is_active", True)),
    }
    if include_runtime_defaults:
        normalized.update(
            {
                "cursor_json": object_value(payload.get("cursor")),
                "health_json": object_value(payload.get("health")),
                "status": str(payload.get("status") or "idle").strip()[:80],
                "last_event_id": None,
                "last_event_at": None,
                "last_cursor": None,
                "dead_letter_count": 0,
            }
        )
    return normalized


async def _verify_webhook_secret(
    db: AsyncSession,
    watcher: ConnectorWatcher,
    provided_secret: str | None,
) -> None:
    stored_secret = (
        await get_secret_value(db, secret_id=watcher.secret_ref, purpose="connector_watcher.verify_webhook")
        if watcher.secret_ref
        else None
    )
    if not provided_secret or not stored_secret or not secrets.compare_digest(provided_secret, stored_secret):
        raise HTTPException(status_code=401, detail="Invalid watcher webhook secret")
