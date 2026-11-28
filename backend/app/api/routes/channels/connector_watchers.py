from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import ConnectorWatcher, User
from ....services.access_control import require_visible_workspace
from ....services.auth import get_current_user
from ....services.connector_watcher_rules import (
    create_connector_watcher_rule,
    list_connector_watcher_rule_decisions,
    list_connector_watcher_rules,
    test_connector_watcher_rule,
    update_connector_watcher_rule,
)
from ....services.connector_watcher_scope import WatcherScope, watcher_scope
from ....services.connector_watcher_service import (
    authenticate_webhook_call,
    create_connector_watcher,
    ingest_connector_poll_events,
    ingest_connector_webhook_event,
    list_connector_watcher_events,
    list_connector_watchers,
    retry_connector_watcher_event,
    update_connector_watcher,
)
from ....services.data_access.machine_principal import authenticating_owner
from ....services.secure_work import require_work_operator

router = APIRouter(prefix="/api/v1/connector-watchers", tags=["connector-watchers"])


async def _operator_scope(db: AsyncSession, current_user: User) -> WatcherScope:
    # The platform role first, then the Workspaces the caller's watcher records lie in (None: a platform admin).
    await require_work_operator(db, current_user)
    return await watcher_scope(db, current_user)


@router.get("")
async def get_connector_watchers(
    project_id: str | None = None,
    include_inactive: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await _operator_scope(db, current_user)
    project_id = (project_id or "").strip() or None
    await require_visible_workspace(db, current_user.id, project_id)
    return {
        "items": await list_connector_watchers(
            db,
            scope=scope,
            project_id=project_id,
            include_inactive=include_inactive,
        )
    }


@router.post("")
async def post_connector_watcher(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await _operator_scope(db, current_user)
    result = await create_connector_watcher(db, current_user=current_user, scope=scope, payload=payload)
    await db.commit()
    return result


@router.put("/{watcher_id}")
async def put_connector_watcher(
    watcher_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await _operator_scope(db, current_user)
    result = await update_connector_watcher(
        db, watcher_id=watcher_id, current_user=current_user, scope=scope, payload=payload
    )
    await db.commit()
    return result


@router.get("/events")
async def get_connector_watcher_events(
    watcher_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await _operator_scope(db, current_user)
    return {
        "items": await list_connector_watcher_events(
            db,
            scope=scope,
            watcher_id=(watcher_id or "").strip() or None,
            status=(status or "").strip() or None,
            limit=limit,
        )
    }


@router.get("/rules")
async def get_connector_watcher_rules(
    project_id: str | None = None,
    include_inactive: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await _operator_scope(db, current_user)
    project_id = (project_id or "").strip() or None
    await require_visible_workspace(db, current_user.id, project_id)
    return {
        "items": await list_connector_watcher_rules(
            db,
            scope=scope,
            project_id=project_id,
            include_inactive=include_inactive,
        )
    }


@router.post("/rules")
async def post_connector_watcher_rule(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await _operator_scope(db, current_user)
    result = await create_connector_watcher_rule(db, current_user=current_user, scope=scope, payload=payload)
    await db.commit()
    return result


@router.put("/rules/{rule_id}")
async def put_connector_watcher_rule(
    rule_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await _operator_scope(db, current_user)
    result = await update_connector_watcher_rule(
        db, rule_id=rule_id, current_user=current_user, scope=scope, payload=payload
    )
    await db.commit()
    return result


@router.post("/rules/{rule_id}/test")
async def post_connector_watcher_rule_test(
    rule_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await _operator_scope(db, current_user)
    return await test_connector_watcher_rule(db, rule_id=rule_id, scope=scope, payload=payload)


@router.get("/rule-decisions")
async def get_connector_watcher_rule_decisions(
    event_id: str | None = None,
    rule_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await _operator_scope(db, current_user)
    return {
        "items": await list_connector_watcher_rule_decisions(
            db,
            scope=scope,
            event_id=(event_id or "").strip() or None,
            rule_id=(rule_id or "").strip() or None,
            limit=limit,
        )
    }


@router.post("/{watcher_id}/poll")
async def post_connector_watcher_poll(
    watcher_id: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await _operator_scope(db, current_user)
    result = await ingest_connector_poll_events(
        db,
        watcher_id=watcher_id,
        current_user=current_user,
        scope=scope,
        payload=payload or {},
    )
    await db.commit()
    return result


@router.post("/events/{event_id}/retry")
async def post_connector_watcher_event_retry(
    event_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await _operator_scope(db, current_user)
    result = await retry_connector_watcher_event(db, event_id=event_id, current_user=current_user, scope=scope)
    await db.commit()
    return result


@router.post("/events/{event_id}/replay")
async def post_connector_watcher_event_replay(
    event_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await _operator_scope(db, current_user)
    result = await retry_connector_watcher_event(db, event_id=event_id, current_user=current_user, scope=scope)
    await db.commit()
    return result


@router.post("/{watcher_id}/webhook")
async def post_connector_watcher_webhook(
    watcher_id: str,
    request: Request,
    x_watcher_secret: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    async with authenticating_owner(db, ConnectorWatcher, watcher_id, owner_column="created_by") as owner:
        watcher = await authenticate_webhook_call(db, watcher_id=watcher_id, provided_secret=x_watcher_secret,
                                                  private=owner.private)
    body = await request.json()
    payload = body if isinstance(body, dict) else {"payload": body}
    result = await ingest_connector_webhook_event(db, watcher=watcher, payload=payload)
    await db.commit()
    return result
