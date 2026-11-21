"""Output channel helpers for the task scheduler."""

from __future__ import annotations

import json
from typing import Any


def load_channel_config_payload(raw_config: Any) -> dict[str, Any]:
    if isinstance(raw_config, dict):
        return dict(raw_config)
    if isinstance(raw_config, str):
        try:
            parsed = json.loads(raw_config)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def resolve_output_channel_target(task, channel_model, channel_config: dict[str, Any]) -> str:
    task_config = dict(task.config or {})
    for key in (
        "output_target",
        "output_channel_target",
        "channel_target",
        "default_target",
        "target",
        "recipient",
        "to_address",
        "channel",
        "channel_id",
        "conversation_target",
    ):
        value = task_config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in (
        "default_target",
        "target",
        "recipient",
        "to_address",
        "channel",
        "channel_id",
        "conversation_target",
    ):
        value = channel_config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def format_task_output_message(task, task_run) -> str:
    lines = [
        f"Task run finished: {task.name}",
        f"Status: {task_run.status}",
        f"Run ID: {task_run.id}",
    ]
    if task_run.session_id:
        lines.append(f"Session: /chat?session_id={task_run.session_id}")
    if task_run.error:
        lines.extend(["", "Error:", task_run.error.strip()])

    output_payload = task_run.output if isinstance(task_run.output, dict) else {}
    if output_payload:
        lines.append("")
        lines.append("Summary:")
        for key in (
            "response",
            "status",
            "matching_tickets",
            "processed",
            "skipped",
            "failed",
            "step_count",
            "step_statuses",
        ):
            value = output_payload.get(key)
            if value in (None, "", [], {}):
                continue
            rendered = ", ".join(str(item) for item in value[:12]) if isinstance(value, list) else str(value)
            if len(rendered) > 1200:
                rendered = rendered[:1200].rstrip() + "..."
            lines.append(f"- {key}: {rendered}")
    return "\n".join(lines)


async def deliver_task_output_channel(db, task, task_run) -> dict[str, Any] | None:
    task_config = dict(task.config or {})
    channel_id = task_config.get("output_channel_id")
    if not channel_id:
        return None

    from ...plugins import plugin_manager
    from ...services.channel_config import ChannelConfigService

    channel_model = await ChannelConfigService.get_model(db, int(channel_id))
    if channel_model is None:
        return {"status": "error", "reason": f"output channel {channel_id} not found"}
    if not channel_model.enabled:
        return {"status": "error", "reason": f"output channel {channel_id} is disabled"}

    channel_config = load_channel_config_payload(channel_model.config)
    target = resolve_output_channel_target(task, channel_model, channel_config)
    if not target:
        return {
            "status": "error",
            "reason": "output channel target is not configured; set output_target on the task or default_target on the channel",
            "channel_id": channel_model.id,
            "channel_name": channel_model.name,
        }

    plugin = plugin_manager.get_channel(str(channel_model.id))
    if plugin is None:
        reload_config = dict(channel_config)
        reload_config["enabled"] = channel_model.enabled
        reload_config["__channel_id"] = str(channel_model.id)
        reload_config["__channel_name"] = channel_model.name
        reload_config["__channel_project_id"] = channel_model.project_id
        await plugin_manager.reload_channel(str(channel_model.id), channel_model.plugin_id, reload_config)
        plugin = plugin_manager.get_channel(str(channel_model.id))
    if plugin is None:
        return {
            "status": "error",
            "reason": f"channel plugin {channel_model.plugin_id} could not be started",
            "channel_id": channel_model.id,
            "channel_name": channel_model.name,
        }

    kwargs: dict[str, Any] = {}
    if channel_model.plugin_id == "email":
        kwargs["subject"] = f"Task output · {task.name} · {task_run.status}"
    sent = await plugin.send_message(target, format_task_output_message(task, task_run), **kwargs)
    return {
        "status": "sent" if sent else "error",
        "channel_id": channel_model.id,
        "channel_name": channel_model.name,
        "plugin_id": channel_model.plugin_id,
        "target": target,
    }
