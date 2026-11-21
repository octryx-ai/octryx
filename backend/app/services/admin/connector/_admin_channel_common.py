"""Channel payload serialization and the channel audit writer."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...channel_config.secret_fields import mask_channel_config


def channel_webhook_url(request: Request, channel_id: int | None, plugin_id: str) -> str | None:
    if channel_id is None:
        return None
    if plugin_id in {"msteams", "slack"}:
        return str(request.url_for("channel_instance_webhook", channel_id=str(channel_id)))
    return None


def serialize_channel_config(request: Request, cfg: Any, *, plugin_manager: Any) -> dict[str, Any]:
    info = plugin_manager.get_plugin_info(cfg.plugin_id)
    # Secrets are write-only: the browser gets has_value, never the credential.
    config, secret_fields = mask_channel_config(cfg.config or {}, info.get("config_fields", []))
    return {
        "id": cfg.id,
        "plugin_id": cfg.plugin_id,
        "name": cfg.name,
        "description": info.get("description", ""),
        "project_id": cfg.project_id,
        "project_name": cfg.project_name,
        "enabled": cfg.enabled,
        "config": config,
        "secret_fields": secret_fields,
        "status": plugin_manager.get_channel_status(str(cfg.id)),
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
        "config_fields": info.get("config_fields", []),
        "webhook_url": channel_webhook_url(request, cfg.id, cfg.plugin_id),
    }


async def audit_channel(
    db: AsyncSession,
    *,
    user_id: str,
    action: str,
    channel_id: str,
    details: dict[str, Any],
) -> None:
    from ....models.runtime.audit import AuditLog

    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            resource_type="channel_plugin",
            resource_id=channel_id,
            details=details,
        )
    )
    await db.commit()
