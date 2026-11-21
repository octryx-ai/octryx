"""Auto-extracted router module: panel_webhooks."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_webhook_panel import (
    OutboundWebhookCreateRequest,
    OutboundWebhookUpdateRequest,
    WebhookCreateRequest,
    WebhookUpdateRequest,
)
from app.services.admin.connector.admin_webhook_service import (
    create_webhook as admin_create_webhook,
)
from app.services.admin.connector.admin_webhook_service import (
    delete_webhook as admin_delete_webhook,
)
from app.services.admin.connector.admin_webhook_service import (
    list_webhooks as admin_list_webhooks,
)
from app.services.admin.connector.admin_webhook_service import (
    update_webhook as admin_update_webhook,
)
from app.services.outbound_webhook import (
    create_outbound_webhook as admin_create_outbound_webhook,
)
from app.services.outbound_webhook import (
    delete_outbound_webhook as admin_delete_outbound_webhook,
)
from app.services.outbound_webhook import (
    list_outbound_webhook_deliveries as admin_list_outbound_webhook_deliveries,
)
from app.services.outbound_webhook import (
    list_outbound_webhooks as admin_list_outbound_webhooks,
)
from app.services.outbound_webhook import (
    update_outbound_webhook as admin_update_outbound_webhook,
)
from app.web._helpers.api_guards import _require_admin_api

from ...services.access_control import require_existing_workspace
from ...services.connector_watcher_rules import (
    list_connector_watcher_rule_decisions,
    list_connector_watcher_rules,
)
from ...services.connector_watcher_service import list_connector_watcher_events, list_connector_watchers

router = APIRouter()


@router.get("/chat/api/panel/webhooks")
async def panel_list_webhooks(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_webhooks(db))


@router.post("/chat/api/panel/webhooks")
async def panel_create_webhook(
    payload: WebhookCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_admin_api(request, db)
    await require_existing_workspace(db, payload.project_id)
    return JSONResponse(await admin_create_webhook(db, user_id=user.id, payload=payload.model_dump()))


@router.put("/chat/api/panel/webhooks/{webhook_id}")
async def panel_update_webhook(
    webhook_id: str,
    payload: WebhookUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    await require_existing_workspace(db, payload.project_id)
    return JSONResponse(
        await admin_update_webhook(db, webhook_id=webhook_id, payload=payload.model_dump(exclude_none=True))
    )


@router.delete("/chat/api/panel/webhooks/{webhook_id}")
async def panel_delete_webhook(webhook_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_delete_webhook(db, webhook_id=webhook_id))


@router.get("/chat/api/panel/outbound-webhooks")
async def panel_list_outbound_webhooks(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_outbound_webhooks(db))


@router.post("/chat/api/panel/outbound-webhooks")
async def panel_create_outbound_webhook(
    payload: OutboundWebhookCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_admin_api(request, db)
    await require_existing_workspace(db, payload.project_id)
    return JSONResponse(
        await admin_create_outbound_webhook(db, current_user=user, payload=payload.model_dump(exclude_none=True))
    )


@router.put("/chat/api/panel/outbound-webhooks/{webhook_id}")
async def panel_update_outbound_webhook(
    webhook_id: str,
    payload: OutboundWebhookUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    await require_existing_workspace(db, payload.project_id)
    return JSONResponse(
        await admin_update_outbound_webhook(db, webhook_id=webhook_id, payload=payload.model_dump(exclude_none=True))
    )


@router.delete("/chat/api/panel/outbound-webhooks/{webhook_id}")
async def panel_delete_outbound_webhook(webhook_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_delete_outbound_webhook(db, webhook_id=webhook_id))


@router.get("/chat/api/panel/outbound-webhook-deliveries")
async def panel_list_outbound_webhook_deliveries(
    request: Request,
    status: str = "",
    webhook_id: str = "",
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_list_outbound_webhook_deliveries(
            db,
            status_filter=status.strip() or None,
            webhook_id=webhook_id.strip() or None,
            limit=limit,
        )
    )


@router.get("/chat/api/panel/connector-watchers")
async def panel_list_connector_watchers(
    request: Request,
    project_id: str = "",
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await list_connector_watchers(
            db,
            scope=None,  # a platform admin: every Workspace
            project_id=project_id.strip() or None,
            include_inactive=True,
        )
    )


@router.get("/chat/api/panel/connector-watcher-events")
async def panel_list_connector_watcher_events(
    request: Request,
    watcher_id: str = "",
    status: str = "",
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await list_connector_watcher_events(
            db,
            scope=None,  # a platform admin: every Workspace
            watcher_id=watcher_id.strip() or None,
            status=status.strip() or None,
            limit=limit,
        )
    )


@router.get("/chat/api/panel/connector-watcher-rules")
async def panel_list_connector_watcher_rules(
    request: Request,
    project_id: str = "",
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await list_connector_watcher_rules(
            db,
            scope=None,  # a platform admin: every Workspace
            project_id=project_id.strip() or None,
            include_inactive=True,
        )
    )


@router.get("/chat/api/panel/connector-watcher-rule-decisions")
async def panel_list_connector_watcher_rule_decisions(
    request: Request,
    event_id: str = "",
    rule_id: str = "",
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await list_connector_watcher_rule_decisions(
            db,
            scope=None,  # a platform admin: every Workspace
            event_id=event_id.strip() or None,
            rule_id=rule_id.strip() or None,
            limit=limit,
        )
    )
