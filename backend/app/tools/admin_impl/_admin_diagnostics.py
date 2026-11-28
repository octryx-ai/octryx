"""Admin tools for diagnostics and audit visibility."""

from __future__ import annotations

from typing import Any

from app.tools.context import ToolContext

from ._admin_common import _require_admin, _require_admin_or_operator


class AdminGetThreadDiagnosticsTool:
    name = "admin_get_thread_diagnostics"
    description = (
        "Inspect a thread/session and return a diagnostic snapshot with messages, tool calls, traces, "
        "runtime attempts and likely failure signals. Admin/operator only. "
        "If session_id is omitted, the current chat session is inspected."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if err := _require_admin_or_operator(context):
            return {"error": err}
        if not context.db:
            return {"error": "No database connection"}

        from sqlalchemy import select

        from ...models import Message, Session, ToolCall, TurnTrace

        session_id = str(params.get("session_id") or context.session_id or "").strip()
        if not session_id:
            return {"error": "session_id is required"}
        session = await context.db.get(Session, session_id)
        from ...services.project.private_workspace import refuse_foreign_private  # noqa: PLC0415

        # Somebody else's private Workspace is not there for an admin or operator.
        if session is not None and session.project_id and await refuse_foreign_private(
                context.db, session.project_id, str(context.user_id)):
            session = None
        if session is not None and not session.project_id and str(session.user_id) != str(context.user_id):
            # A person's sessions without a Workspace (MCP tool calls, ingested summaries)
            # are theirs alone too.
            session = None
        if not session:
            return {"error": f"Session '{session_id}' not found"}

        messages = (
            (
                await context.db.execute(
                    select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        tool_calls = (
            (
                await context.db.execute(
                    select(ToolCall).where(ToolCall.session_id == session_id).order_by(ToolCall.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        traces = (
            (
                await context.db.execute(
                    select(TurnTrace).where(TurnTrace.session_id == session_id).order_by(TurnTrace.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

        findings: list[str] = []
        if not any(call.status == "success" for call in tool_calls) and traces:
            findings.append("No successful tool execution was persisted for this session.")
        if messages and messages[-1].role == "assistant":
            final_content = (messages[-1].content or "").strip()
            if "<tool_call>" in final_content and not (messages[-1].tool_calls or []):
                findings.append(
                    "Assistant message contains pseudo tool-call markup in plain text without real tool_calls."
                )
            if not final_content:
                findings.append("Final assistant message is empty.")

        runtime_attempts: list[dict[str, Any]] = []
        for trace in traces[-6:]:
            raw_output = trace.raw_output or {}
            for attempt in raw_output.get("runtime_attempts") or []:
                runtime_attempts.append(dict(attempt))

        return {
            "session": {
                "id": session.id,
                "status": session.status,
                "agent_type": session.agent_type,
                "project_id": session.project_id,
                "metadata": dict(session.metadata_ or {}),
            },
            "message_count": len(messages),
            "messages": [
                {
                    "id": message.id,
                    "role": message.role,
                    "content": (message.content or "")[:600],
                    "tool_calls": message.tool_calls or [],
                    "model": message.model,
                    "created_at": message.created_at.isoformat() if message.created_at else None,
                }
                for message in messages[-8:]
            ],
            "tool_call_count": len(tool_calls),
            "tool_calls": [
                {
                    "id": call.id,
                    "tool_name": call.tool_name,
                    "status": call.status,
                    "parameters": call.parameters,
                    "duration_ms": call.duration_ms,
                    "created_at": call.created_at.isoformat() if call.created_at else None,
                }
                for call in tool_calls[-12:]
            ],
            "trace_count": len(traces),
            "runtime_attempts": runtime_attempts[-12:],
            "findings": findings,
        }


class AdminViewAuditLogTool:
    name = "admin_view_audit_log"
    description = (
        "View recent audit log entries. Admin only. "
        "Optional filters: user_id, action, resource_type, limit (default 20, max 100)."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if err := _require_admin(context):
            return {"error": err}
        if not context.db:
            return {"error": "No database connection"}

        from sqlalchemy import select

        from ...models import AuditLog
        from ...services.audit_trail.workspace_scope import owner_known

        limit = min(int(params.get("limit") or 20), 100)
        query = select(AuditLog).where(owner_known()).order_by(AuditLog.created_at.desc()).limit(limit)
        if params.get("user_id"):
            query = query.where(AuditLog.user_id == str(params["user_id"]))
        if params.get("action"):
            query = query.where(AuditLog.action == str(params["action"]))
        if params.get("resource_type"):
            query = query.where(AuditLog.resource_type == str(params["resource_type"]))

        result = await context.db.execute(query)
        entries = result.scalars().all()
        return {
            "entries": [
                {
                    "id": entry.id,
                    "user_id": entry.user_id,
                    "action": entry.action,
                    "resource_type": entry.resource_type,
                    "resource_id": getattr(entry, "resource_id", None),
                    "ip_address": getattr(entry, "ip_address", None),
                    "created_at": entry.created_at.isoformat() if entry.created_at else None,
                }
                for entry in entries
            ],
            "count": len(entries),
        }


class AdminGetUsageStatsTool:
    name = "admin_get_usage_stats"
    description = (
        "Get token usage and cost statistics. Admin/operator only. "
        "Optional: filter by user_id, project_id, or days (default: last 7 days)."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if err := _require_admin_or_operator(context):
            return {"error": err}
        if not context.db:
            return {"error": "No database connection"}

        import datetime

        from sqlalchemy import func, select

        from ...models import UsageEvent

        days = int(params.get("days") or 7)
        since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

        query = select(
            func.sum(UsageEvent.input_tokens).label("input_tokens"),
            func.sum(UsageEvent.output_tokens).label("output_tokens"),
            func.count(UsageEvent.id).label("request_count"),
        ).where(UsageEvent.created_at >= since)
        if params.get("user_id"):
            query = query.where(UsageEvent.user_id == str(params["user_id"]))
        if params.get("project_id"):
            query = query.where(UsageEvent.project_id == str(params["project_id"]))

        result = await context.db.execute(query)
        row = result.one_or_none()

        breakdown_query = (
            select(
                UsageEvent.model,
                func.sum(UsageEvent.input_tokens).label("input"),
                func.sum(UsageEvent.output_tokens).label("output"),
                func.count(UsageEvent.id).label("requests"),
            )
            .where(UsageEvent.created_at >= since)
            .group_by(UsageEvent.model)
            .order_by(func.count(UsageEvent.id).desc())
            .limit(10)
        )
        if params.get("user_id"):
            breakdown_query = breakdown_query.where(UsageEvent.user_id == str(params["user_id"]))

        breakdown_result = await context.db.execute(breakdown_query)
        breakdown = [
            {"model": row.model, "input_tokens": row.input, "output_tokens": row.output, "requests": row.requests}
            for row in breakdown_result.all()
        ]

        return {
            "period_days": days,
            "totals": {
                "input_tokens": int(row.input_tokens or 0) if row else 0,
                "output_tokens": int(row.output_tokens or 0) if row else 0,
                "request_count": int(row.request_count or 0) if row else 0,
            },
            "by_model": breakdown,
        }


class AdminListSessionsTool:
    name = "admin_list_sessions"
    description = (
        "List chat sessions across all users. Admin only. "
        "Optional filter: user_id, status (running/active/archived), limit (default 20)."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if err := _require_admin(context):
            return {"error": err}
        if not context.db:
            return {"error": "No database connection"}

        from sqlalchemy import or_, select

        from ...models import Session, User

        limit = min(int(params.get("limit") or 20), 200)
        from ...services.project.private_workspace import hidden_private_ids  # noqa: PLC0415

        hidden = await hidden_private_ids(context.db, str(context.user_id))
        query = select(Session).order_by(Session.last_activity_at.desc()).limit(limit)
        if hidden:  # Other people's private Workspaces stay out of the list
            query = query.where(or_(Session.project_id.is_(None), Session.project_id.not_in(sorted(hidden))))
        if params.get("user_id"):
            query = query.where(Session.user_id == str(params["user_id"]))
        if params.get("status"):
            query = query.where(Session.status == str(params["status"]))

        result = await context.db.execute(query)
        sessions = result.scalars().all()
        out = []
        for session in sessions:
            user_result = await context.db.execute(select(User.username).where(User.id == session.user_id))
            username = user_result.scalar_one_or_none() or session.user_id
            out.append(
                {
                    "id": session.id,
                    "title": session.title or "Untitled",
                    "status": session.status,
                    "user": username,
                    "created_at": session.created_at.isoformat() if session.created_at else None,
                    "updated_at": session.last_activity_at.isoformat() if session.last_activity_at else None,
                }
            )
        return {"sessions": out, "count": len(out)}


__all__ = [
    "AdminGetThreadDiagnosticsTool",
    "AdminGetUsageStatsTool",
    "AdminListSessionsTool",
    "AdminViewAuditLogTool",
]
