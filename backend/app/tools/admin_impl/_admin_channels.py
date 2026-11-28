"""Admin tools for channel management."""

from __future__ import annotations

import json
from typing import Any

from app.services.error_facts import error_text
from app.tools.context import ToolContext

from ._admin_common import _require_admin, _require_admin_or_operator, _resolve_channel, _resolve_project_id


class AdminListChannelsTool:
    name = "admin_list_channels"
    description = (
        "List configured delivery channels. Admin/operator only. "
        "Returns channel id, name, plugin type, project assignment, and enabled status."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if err := _require_admin_or_operator(context):
            return {"error": err}
        if not context.db:
            return {"error": "No database connection"}

        from ...services.channel_config import ChannelConfigService

        channels = await ChannelConfigService.get_all(context.db)
        return {
            "channels": [
                {
                    "id": channel.id,
                    "plugin_id": channel.plugin_id,
                    "name": channel.name,
                    "project_id": channel.project_id,
                    "project_name": channel.project_name,
                    "enabled": channel.enabled,
                    "updated_at": channel.updated_at.isoformat() if channel.updated_at else None,
                }
                for channel in channels
            ],
            "count": len(channels),
        }


class AdminCreateChannelTool:
    name = "admin_create_channel"
    description = (
        "Create a new channel instance such as Slack, Teams or Email. "
        "Admin only. Requires plugin_id, name and config. "
        "Optional: project_id/project_name and enabled."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if err := _require_admin(context):
            return {"error": err}
        if not context.db:
            return {"error": "No database connection"}

        plugin_id = str(params.get("plugin_id") or "").strip()
        name = str(params.get("name") or "").strip()
        enabled = bool(params.get("enabled", True))
        config = params.get("config") or {}
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except json.JSONDecodeError as exc:
                return {"error": f"config must be valid JSON: {exc}"}
        if not isinstance(config, dict):
            return {"error": "config must be an object"}
        if not plugin_id:
            return {"error": "plugin_id is required"}
        if not name:
            return {"error": "name is required"}

        project_id, project_error = await _resolve_project_id(
            context,
            params.get("project_id") or params.get("project_name"),
        )
        if project_error:
            return {"error": project_error}

        from ...plugins import plugin_manager
        from ...services.channel_config import ChannelConfigService
        from ...services.channel_config.credentials import CHANNEL_START, channel_runtime_config

        channel = await ChannelConfigService.create(
            context.db,
            plugin_id=plugin_id,
            name=name,
            project_id=project_id,
            enabled=enabled,
            config=config,
        )
        status = "stopped"
        try:
            await plugin_manager.reload_channel(str(channel.id), channel.plugin_id, await channel_runtime_config(
                context.db, channel, purpose=CHANNEL_START))
            status = plugin_manager.get_channel_status(str(channel.id))
        except Exception as exc:
            status = f"error: {error_text('channel_start_failed', exc)}"

        return {
            "status": "created",
            "channel": {
                "id": channel.id,
                "plugin_id": channel.plugin_id,
                "name": channel.name,
                "project_id": channel.project_id,
                "project_name": channel.project_name,
                "enabled": channel.enabled,
                "status": status,
            },
        }


class AdminUpdateChannelTool:
    name = "admin_update_channel"
    description = (
        "Update an existing channel instance such as Slack, Teams or Email. "
        "Admin only. Identify the channel by channel_id or channel_name. "
        "Can rename it, assign a project, enable/disable it, replace config or merge config fields."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if err := _require_admin(context):
            return {"error": err}
        if not context.db:
            return {"error": "No database connection"}

        channel, error = await _resolve_channel(
            context,
            params.get("channel_id") or params.get("channel_name"),
        )
        if error:
            return {"error": error}

        from ...plugins import plugin_manager
        from ...services.channel_config import ChannelConfigService
        from ...services.channel_config.credentials import CHANNEL_START, channel_runtime_config, stored_config
        from ...services.channel_config.secret_fields import mask_channel_config

        config = stored_config(channel.config)
        changes: list[str] = []
        if params.get("config") is not None:
            next_config = params.get("config") or {}
            if isinstance(next_config, str):
                try:
                    next_config = json.loads(next_config)
                except json.JSONDecodeError as exc:
                    return {"error": f"config must be valid JSON: {exc}"}
            if not isinstance(next_config, dict):
                return {"error": "config must be an object"}
            config = dict(next_config)
            changes.append("config replaced")
        if params.get("merge_config") is not None:
            merge_config = params.get("merge_config") or {}
            if isinstance(merge_config, str):
                try:
                    merge_config = json.loads(merge_config)
                except json.JSONDecodeError as exc:
                    return {"error": f"merge_config must be valid JSON: {exc}"}
            if not isinstance(merge_config, dict):
                return {"error": "merge_config must be an object"}
            config.update(merge_config)
            changes.append("config merged")

        project_id, project_error = await _resolve_project_id(
            context,
            params.get("project_id") or params.get("project_name"),
        )
        if project_error:
            return {"error": project_error}
        if params.get("project_id") is not None or params.get("project_name") is not None:
            changes.append(f"project_id → {project_id or 'none'}")

        updated = await ChannelConfigService.update(
            context.db,
            int(channel.id),
            name=str(params.get("name") or "").strip() if params.get("name") is not None else None,
            project_id=project_id
            if (params.get("project_id") is not None or params.get("project_name") is not None)
            else None,
            enabled=bool(params.get("enabled")) if params.get("enabled") is not None else None,
            config=config,
        )
        if not updated:
            return {"error": f"Channel '{channel.id}' could not be updated"}

        status = "stopped"
        try:
            await plugin_manager.reload_channel(str(updated.id), updated.plugin_id, await channel_runtime_config(
                context.db, updated, purpose=CHANNEL_START))
            status = plugin_manager.get_channel_status(str(updated.id))
        except Exception as exc:
            status = f"error: {error_text('channel_start_failed', exc)}"

        if params.get("name") is not None:
            changes.append(f"name → {updated.name}")
        if params.get("enabled") is not None:
            changes.append(f"enabled → {updated.enabled}")

        return {
            "status": "updated",
            "channel": {
                "id": updated.id,
                "plugin_id": updated.plugin_id,
                "name": updated.name,
                "project_id": updated.project_id,
                "project_name": updated.project_name,
                "enabled": updated.enabled,
                # Write-only secrets: the transcript never carries a channel credential.
                "config": mask_channel_config(
                    updated.config or {}, plugin_manager.get_plugin_info(updated.plugin_id).get("config_fields", [])
                )[0],
                "status": status,
            },
            "changes": changes,
        }


__all__ = [
    "AdminCreateChannelTool",
    "AdminListChannelsTool",
    "AdminUpdateChannelTool",
]
