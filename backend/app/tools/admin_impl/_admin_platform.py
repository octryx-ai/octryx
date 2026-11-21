"""Admin tools for webhooks and platform status."""

from __future__ import annotations

from typing import Any

from app.tools.context import ToolContext

from ._admin_common import _require_admin_or_operator


class AdminListWebhooksTool:
    name = "admin_list_webhooks"
    description = "List all configured webhooks. Admin/operator only."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if err := _require_admin_or_operator(context):
            return {"error": err}
        if not context.db:
            return {"error": "No database connection"}

        from sqlalchemy import select

        from ...models import Webhook

        result = await context.db.execute(select(Webhook).order_by(Webhook.name))
        webhooks = result.scalars().all()
        return {
            "webhooks": [
                {
                    "id": webhook.id,
                    "name": webhook.name,
                    "event_type": getattr(webhook, "event_type", ""),
                    "is_active": getattr(webhook, "is_active", True),
                    "created_at": webhook.created_at.isoformat() if getattr(webhook, "created_at", None) else None,
                }
                for webhook in webhooks
            ],
            "count": len(webhooks),
        }


class AdminPlatformStatusTool:
    name = "admin_platform_status"
    description = (
        "Get a full platform status overview: user count, active sessions, "
        "scheduled tasks, recent errors, and MCP server status. "
        "Admin/operator only."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if err := _require_admin_or_operator(context):
            return {"error": err}
        if not context.db:
            return {"error": "No database connection"}

        from sqlalchemy import func, select

        from ...models import Session, Task, User

        user_count = (
            await context.db.execute(select(func.count()).select_from(User).where(User.is_active.is_(True)))
        ).scalar() or 0
        total_users = (await context.db.execute(select(func.count()).select_from(User))).scalar() or 0
        running_sessions = (
            await context.db.execute(select(func.count()).select_from(Session).where(Session.status == "running"))
        ).scalar() or 0
        active_sessions = (
            await context.db.execute(select(func.count()).select_from(Session).where(Session.status == "active"))
        ).scalar() or 0

        task_count = 0
        try:
            task_count = (await context.db.execute(select(func.count()).select_from(Task))).scalar() or 0
        except Exception:
            pass

        from ...plugins.mcp.client import mcp_client_manager

        mcp_status = [
            {
                "name": server.name,
                "connected": await mcp_client_manager.is_connected(server.name),
                "transport": server.transport.value,
            }
            for server in mcp_client_manager.list_servers()
        ]

        return {
            "users": {"active": user_count, "total": total_users},
            "sessions": {"running": running_sessions, "active": active_sessions},
            "scheduled_tasks": task_count,
            "mcp_servers": mcp_status,
        }


__all__ = [
    "AdminListWebhooksTool",
    "AdminPlatformStatusTool",
]
