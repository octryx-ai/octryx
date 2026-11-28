"""Webhooks → Inbound: rotate, test alert, outcome log and samples (automation V3)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...schemas.admin.admin_webhook_panel import WebhookTestRequest
from ...services.admin.connector import admin_webhook_service
from ...services.inbound_alerts.admission import ALERT_FILTERS
from ...services.inbound_alerts.normalize import POLLED_SOURCE_TYPES, SOURCE_LABELS, SOURCE_TYPES
from ...services.inbound_alerts.samples import samples_for
from .._helpers.api_guards import _require_admin_api

router = APIRouter()


@router.get("/chat/api/panel/webhooks/catalog")
async def panel_webhook_catalog(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse({
        "sources": [
            {"key": key, "label": SOURCE_LABELS[key], "polled": key in POLLED_SOURCE_TYPES, "samples": samples_for(key)}
            for key in SOURCE_TYPES
        ],
        "alert_filters": list(ALERT_FILTERS),
    })


@router.get("/chat/api/panel/webhook-events")
async def panel_latest_webhook_events(request: Request, limit: int = 20, db: AsyncSession = Depends(get_db)):
    user = await _require_admin_api(request, db)
    return JSONResponse(await admin_webhook_service.list_webhook_events(db, viewer_id=user.id, limit=limit))


@router.get("/chat/api/panel/webhooks/{webhook_id}/events")
async def panel_webhook_events(webhook_id: str, request: Request, limit: int = 20, db: AsyncSession = Depends(get_db)):
    user = await _require_admin_api(request, db)
    return JSONResponse(await admin_webhook_service.list_webhook_events(db, viewer_id=user.id, webhook_id=webhook_id,
                                                                        limit=limit))


@router.post("/chat/api/panel/webhooks/{webhook_id}/rotate-secret")
async def panel_rotate_webhook_secret(webhook_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await _require_admin_api(request, db)
    return JSONResponse(await admin_webhook_service.rotate_webhook_secret(db, webhook_id=webhook_id, user_id=user.id))


@router.post("/chat/api/panel/webhooks/{webhook_id}/test")
async def panel_test_webhook(
    webhook_id: str, payload: WebhookTestRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    user = await _require_admin_api(request, db)
    return JSONResponse(await admin_webhook_service.send_test_alert(db, webhook_id=webhook_id, viewer_id=user.id,
                                                                    sample=payload.sample))
