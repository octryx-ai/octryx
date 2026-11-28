"""``WS /api/v1/devices/channel``: the outbound connection of an octryx-claude device service."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket

from app.services.devices.channel_protocol import register_channel_handlers

from ....db import async_session_factory
from ....services.agent_gateway.identity import bearer_token
from ....services.devices.channel import DeviceChannelSession
from ....services.devices.jobs_channel import DeviceJobHandlers

router = APIRouter(tags=["devices"])
register_channel_handlers(DeviceJobHandlers())


@router.websocket("/api/v1/devices/channel")
async def device_channel(websocket: WebSocket) -> None:
    await websocket.accept()
    session_factory = getattr(websocket.app.state, "async_session_factory", async_session_factory)
    await DeviceChannelSession(websocket, token=bearer_token(websocket.headers),
                               session_factory=session_factory).run()
