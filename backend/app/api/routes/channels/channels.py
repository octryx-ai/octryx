"""Channel webhook endpoints and listing."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import ChannelConfig, User
from ....services.access_control import require_project_access
from ....services.auth import get_current_user
from ....services.channel_webhook_auth import ChannelWebhookRefusedError, authenticate_channel_webhook
from ....services.data_access.machine_principal import bind_authenticated_owner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/channels", tags=["channels"])


def _default_webhook_response(plugin_id: str, payload: dict) -> JSONResponse:
    if plugin_id == "msteams":
        return JSONResponse({"type": "message", "text": ""})
    if plugin_id == "slack" and payload.get("type") == "url_verification":
        return JSONResponse({"challenge": payload.get("challenge", "")})
    return JSONResponse({"ok": True})


def _resolve_channel_plugin(plugin_id: str, channel_id: str):
    from ....plugins import plugin_manager

    plugin = plugin_manager.get_channel(str(channel_id))
    if plugin is None or plugin.plugin_id != plugin_id:
        raise HTTPException(status_code=404, detail="Channel instance not found")
    return str(channel_id), plugin


async def _handle_channel_webhook(plugin_id: str, request: Request, channel_id: str,
                                  db: AsyncSession) -> JSONResponse:
    # Deny by default: the channel's own authentication runs before the body is parsed or any
    # handler work starts (``services/channel_webhook_auth``).
    resolved_channel_id, plugin = _resolve_channel_plugin(plugin_id, channel_id)
    body_bytes = await request.body()
    try:
        authenticated = await authenticate_channel_webhook(
            plugin, channel_id=resolved_channel_id, headers=request.headers, body=body_bytes
        )
    except ChannelWebhookRefusedError as refused:
        raise HTTPException(status_code=refused.status_code, detail={"code": refused.state}) from None
    if resolved_channel_id.isdigit():
        await bind_authenticated_owner(db, ChannelConfig, int(resolved_channel_id), owner_column=None)
    payload = authenticated.payload

    logger.debug(
        "channel_webhook_received plugin=%s channel=%s scheme=%s odata_type=%s type=%s",
        plugin_id,
        resolved_channel_id,
        authenticated.scheme,
        payload.get("@odata.type", ""),
        payload.get("type", ""),
    )

    try:
        result = await plugin.receive_webhook(payload)
        if result is not None:
            return JSONResponse(result)
    except Exception as exc:
        logger.exception("Webhook handler error for %s#%s: %s", plugin_id, resolved_channel_id, type(exc).__name__)

    return _default_webhook_response(plugin_id, payload)


# Every webhook names its channel (``/{channel_id}/webhook``); there is no per-type route that resolves "the only
# channel of this type".
@router.post("/{channel_id}/webhook")
async def channel_instance_webhook(channel_id: str, request: Request,
                                   db: AsyncSession = Depends(get_db)) -> JSONResponse:
    from ....plugins import plugin_manager

    plugin = plugin_manager.get_channel(str(channel_id))
    if plugin is None:
        raise HTTPException(status_code=404, detail="Channel instance not found")
    return await _handle_channel_webhook(str(plugin.plugin_id), request, channel_id, db)


@router.post("/msteams/{channel_id}/webhook")
async def msteams_instance_webhook(channel_id: str, request: Request,
                                   db: AsyncSession = Depends(get_db)) -> JSONResponse:
    return await _handle_channel_webhook("msteams", request, channel_id, db)


@router.post("/slack/{channel_id}/webhook")
async def slack_instance_webhook(channel_id: str, request: Request,
                                 db: AsyncSession = Depends(get_db)) -> JSONResponse:
    return await _handle_channel_webhook("slack", request, channel_id, db)


@router.get("")
async def list_channels(
    project_id: str = Query(..., description="Project ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """List the active channels of a Workspace the caller belongs to (or any, for an admin)."""
    await require_project_access(db, current_user.id, project_id)
    result = await db.execute(
        select(ChannelConfig).where(
            ChannelConfig.project_id == project_id,
            ChannelConfig.enabled.is_(True),
        )
    )
    channels = list(result.scalars().all())
    return {
        "channels": [
            {
                "id": c.id,
                "name": c.name or c.plugin_id,
                "plugin_id": c.plugin_id,
                "enabled": c.enabled,
            }
            for c in channels
        ],
        "count": len(channels),
    }
