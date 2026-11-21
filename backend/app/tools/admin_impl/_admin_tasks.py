"""Admin tools for task management."""

from __future__ import annotations

import json
from typing import Any

from app.tools.context import ToolContext

from ._admin_common import _require_admin_or_operator, _resolve_channel, _resolve_task


class AdminListTasksTool:
    name = "admin_list_tasks"
    description = (
        "List all scheduled tasks (cron jobs). Admin/operator only. Returns name, schedule, last run time, and status."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if err := _require_admin_or_operator(context):
            return {"error": err}
        if not context.db:
            return {"error": "No database connection"}

        from sqlalchemy import select

        from ...models import Task

        result = await context.db.execute(select(Task).order_by(Task.name))
        tasks = result.scalars().all()
        return {
            "tasks": [
                {
                    "id": task.id,
                    "name": task.name,
                    "cron_expression": getattr(task, "cron_expression", ""),
                    "is_active": getattr(task, "is_active", True),
                    "last_run_at": task.last_run_at.isoformat() if getattr(task, "last_run_at", None) else None,
                    "next_run_at": task.next_run_at.isoformat() if getattr(task, "next_run_at", None) else None,
                }
                for task in tasks
            ],
            "count": len(tasks),
        }


class AdminUpdateTaskTool:
    name = "admin_update_task"
    description = (
        "Update a task configuration. Admin/operator only. "
        "Can rename a task, change active status, replace config, or set an output channel "
        "using output_channel_id/output_channel_name."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if err := _require_admin_or_operator(context):
            return {"error": err}
        if not context.db:
            return {"error": "No database connection"}

        task, error = await _resolve_task(context, params.get("task_id") or params.get("task_name"))
        if error:
            return {"error": error}

        changes: list[str] = []
        if params.get("name") is not None:
            task.name = str(params.get("name") or "").strip() or task.name
            changes.append(f"name → {task.name}")
        if params.get("description") is not None:
            task.description = str(params.get("description") or "")
            changes.append("description updated")
        if params.get("is_active") is not None:
            task.is_active = bool(params.get("is_active"))
            changes.append(f"is_active → {task.is_active}")

        config = dict(task.config or {})
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

        if params.get("output_channel_id") is not None or params.get("output_channel_name") is not None:
            channel, channel_error = await _resolve_channel(
                context,
                params.get("output_channel_id") or params.get("output_channel_name"),
            )
            if channel_error:
                return {"error": channel_error}
            config["output_channel_id"] = int(channel.id)
            config["output_channel_name"] = channel.name
            changes.append(f"output_channel → {channel.name} ({channel.id})")

        if params.get("output_target") is not None:
            output_target = str(params.get("output_target") or "").strip()
            if output_target:
                config["output_target"] = output_target
                changes.append(f"output_target → {output_target}")
            else:
                config.pop("output_target", None)
                changes.append("output_target cleared")

        if params.get("clear_output_channel"):
            config.pop("output_channel_id", None)
            config.pop("output_channel_name", None)
            config.pop("output_target", None)
            changes.append("output_channel cleared")

        task.config = config
        if not changes:
            return {"message": "No changes provided", "task_id": task.id}

        await context.db.commit()
        return {
            "status": "updated",
            "task": {
                "id": task.id,
                "name": task.name,
                "is_active": task.is_active,
                "config": dict(task.config or {}),
            },
            "changes": changes,
        }


__all__ = [
    "AdminListTasksTool",
    "AdminUpdateTaskTool",
]
