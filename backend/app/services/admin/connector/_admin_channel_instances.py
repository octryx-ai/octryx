"""Channel instance lifecycle: list, create, update, delete and reload."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...channel_config import ChannelConfigService
from ...channel_config.credentials import CHANNEL_START, channel_runtime_config
from ...error_facts import error_text
from ._admin_channel_common import audit_channel, channel_webhook_url, serialize_channel_config

# Log records keep the name of the public module these functions were always logged under.
logger = logging.getLogger(__name__.rsplit(".", 1)[0] + ".admin_channel_service")


async def list_configured_channels(
    db: AsyncSession,
    *,
    request: Request,
    plugin_manager: Any,
) -> list[dict[str, Any]]:
    configs = await ChannelConfigService.get_all(db)
    return [serialize_channel_config(request, cfg, plugin_manager=plugin_manager) for cfg in configs]


async def list_available_channels(
    *,
    request: Request,
    plugin_manager: Any,
) -> list[dict[str, Any]]:
    result = []
    for plugin_id in plugin_manager.get_known_plugin_ids():
        info = plugin_manager.get_plugin_info(plugin_id)
        result.append(
            {
                "id": None,
                "plugin_id": plugin_id,
                "name": info.get("name", plugin_id),
                "description": info.get("description", ""),
                "project_id": None,
                "project_name": None,
                "enabled": False,
                "config": {},
                "status": "stopped",
                "updated_at": None,
                "config_fields": info.get("config_fields", []),
                "webhook_url": channel_webhook_url(request, None, plugin_id),
            }
        )
    return result


async def get_channel_details(
    db: AsyncSession,
    *,
    request: Request,
    channel_id: int,
    plugin_manager: Any,
) -> dict[str, Any]:
    cfg = await ChannelConfigService.get(db, channel_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    info = plugin_manager.get_plugin_info(cfg.plugin_id)
    return {
        **serialize_channel_config(request, cfg, plugin_manager=plugin_manager),
        "description": info.get("description", ""),
        "config_fields": info.get("config_fields", []),
    }


async def create_channel(
    db: AsyncSession,
    *,
    request: Request,
    body: dict[str, Any],
    admin_id: str,
    plugin_manager: Any,
) -> dict[str, Any]:
    plugin_id = str(body.get("plugin_id") or "").strip()
    name = str(body.get("name") or "").strip()
    project_id = str(body.get("project_id") or "").strip() or None
    enabled = bool(body.get("enabled", False))
    config = body.get("config", {})

    if not plugin_id:
        raise HTTPException(status_code=400, detail="plugin_id is required")
    if not name:
        info = plugin_manager.get_plugin_info(plugin_id)
        name = info.get("name", plugin_id)

    cfg = await ChannelConfigService.create(
        db,
        plugin_id=plugin_id,
        name=name,
        project_id=project_id,
        enabled=enabled,
        config=config,
    )

    status = "stopped"
    try:
        await plugin_manager.reload_channel(str(cfg.id), cfg.plugin_id,
                                            await channel_runtime_config(db, cfg, purpose=CHANNEL_START))
        status = plugin_manager.get_channel_status(str(cfg.id))
    except Exception as exc:
        logger.warning(
                "Channel start failed for %s#%s: %s", cfg.plugin_id, cfg.id, error_text("channel_start_failed", exc)
            )
        status = "error"

    await audit_channel(
        db,
        user_id=admin_id,
        action="channel_created",
        channel_id=str(cfg.id),
        details={"plugin_id": cfg.plugin_id, "enabled": cfg.enabled, "status": status},
    )
    return {**serialize_channel_config(request, cfg, plugin_manager=plugin_manager), "status": status}


async def _reload_saved_channel(db: AsyncSession, plugin_manager: Any, cfg: Any) -> str:
    try:
        await plugin_manager.reload_channel(str(cfg.id), cfg.plugin_id,
                                            await channel_runtime_config(db, cfg, purpose=CHANNEL_START))
        status = plugin_manager.get_channel_status(str(cfg.id))
    except Exception as exc:
        logger.warning(
                "Channel reload failed for %s#%s: %s", cfg.plugin_id, cfg.id, error_text("channel_reload_failed", exc)
            )
        status = "error"
    return status


async def update_channel(
    db: AsyncSession,
    *,
    request: Request,
    channel_id: int,
    body: dict[str, Any],
    admin_id: str,
    plugin_manager: Any,
) -> dict[str, Any]:
    name = body.get("name")
    if name is not None:
        name = str(name).strip()
    project_id = body.get("project_id")
    if project_id is not None:
        project_id = str(project_id).strip() or None
    enabled = bool(body.get("enabled", False))
    config = body.get("config", {})

    cfg = await ChannelConfigService.update(
        db,
        channel_id,
        name=name,
        project_id=project_id,
        enabled=enabled,
        config=config or {},
    )
    if cfg is None:
        raise HTTPException(status_code=404, detail="Channel not found")

    status = await _reload_saved_channel(db, plugin_manager, cfg)

    await audit_channel(
        db,
        user_id=admin_id,
        action="channel_config_updated",
        channel_id=str(cfg.id),
        details={"plugin_id": cfg.plugin_id, "enabled": enabled, "status": status},
    )
    return {**serialize_channel_config(request, cfg, plugin_manager=plugin_manager), "status": status}


async def delete_channel(
    db: AsyncSession,
    *,
    channel_id: int,
    admin_id: str,
    plugin_manager: Any,
) -> dict[str, Any]:
    cfg = await ChannelConfigService.get(db, channel_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="Channel not found")

    await plugin_manager.stop_channel(str(channel_id))
    deleted = await ChannelConfigService.delete(db, channel_id)
    await audit_channel(
        db,
        user_id=admin_id,
        action="channel_deleted",
        channel_id=str(channel_id),
        details={"plugin_id": cfg.plugin_id, "deleted": deleted},
    )
    return {"deleted": deleted, "id": channel_id}


async def reload_channel(
    db: AsyncSession,
    *,
    channel_id: int,
    admin_id: str,
    plugin_manager: Any,
) -> dict[str, Any]:
    cfg = await ChannelConfigService.get(db, channel_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="Channel not found")

    try:
        await plugin_manager.reload_channel(str(cfg.id), cfg.plugin_id,
                                            await channel_runtime_config(db, cfg, purpose=CHANNEL_START))
        status = plugin_manager.get_channel_status(str(cfg.id))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Channel could not be reloaded. {error_text('channel_reload_failed', exc)}",
        ) from exc

    await audit_channel(
        db,
        user_id=admin_id,
        action="channel_reloaded",
        channel_id=str(channel_id),
        details={"plugin_id": cfg.plugin_id, "status": status},
    )
    return {"id": channel_id, "plugin_id": cfg.plugin_id, "status": status}
