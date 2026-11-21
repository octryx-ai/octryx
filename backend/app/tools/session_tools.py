"""Session-scoped tools – todo list management stored in session metadata."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..models import Session
from .context import ToolContext


class TodoReadTool:
    name = "todo_read"
    description = (
        "Read the current todo list for this agent session. "
        "Returns all todos with their id, subject, status (pending/in_progress/completed), and optional description. "
        "Use this to check progress and decide what to work on next."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        todos = await self._load_todos(context)
        pending = [t for t in todos if t.get("status") == "pending"]
        in_progress = [t for t in todos if t.get("status") == "in_progress"]
        completed = [t for t in todos if t.get("status") == "completed"]
        return {
            "todos": todos,
            "summary": {
                "total": len(todos),
                "pending": len(pending),
                "in_progress": len(in_progress),
                "completed": len(completed),
            },
        }

    async def _load_todos(self, context: ToolContext) -> list[dict]:
        if not context.db or not context.session_id:
            return []
        try:
            result = await context.db.execute(select(Session).where(Session.id == context.session_id))
            session = result.scalar_one_or_none()
            if not session:
                return []
            return list((session.metadata_ or {}).get("todos") or [])
        except SQLAlchemyError:
            return []


class TodoWriteTool:
    name = "todo_write"
    description = (
        "Update the todo list for this agent session. "
        "Replaces the entire todo list with the provided todos. "
        "Each todo must have: id (string), subject (string), status (pending|in_progress|completed). "
        "Optional fields: description (string). "
        "Use to track progress on multi-step tasks."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        todos = params.get("todos")
        if todos is None:
            return {"error": "todos is required"}
        if not isinstance(todos, list):
            return {"error": "todos must be a list"}

        valid_statuses = {"pending", "in_progress", "completed"}
        cleaned = []
        for i, todo in enumerate(todos):
            if not isinstance(todo, dict):
                return {"error": f"todos[{i}] must be an object"}
            if not todo.get("id"):
                return {"error": f"todos[{i}].id is required"}
            if not todo.get("subject"):
                return {"error": f"todos[{i}].subject is required"}
            status = todo.get("status", "pending")
            if status not in valid_statuses:
                return {"error": f"todos[{i}].status must be one of: {', '.join(sorted(valid_statuses))}"}
            cleaned.append(
                {
                    "id": str(todo["id"]),
                    "subject": str(todo["subject"]),
                    "status": status,
                    "description": str(todo.get("description") or ""),
                }
            )

        if not context.db or not context.session_id:
            return {"error": "No active database session"}

        try:
            result = await context.db.execute(select(Session).where(Session.id == context.session_id))
            session = result.scalar_one_or_none()
            if not session:
                return {"error": "Session not found"}

            metadata = dict(session.metadata_ or {})
            metadata["todos"] = cleaned
            session.metadata_ = metadata
            await context.db.commit()
        except SQLAlchemyError as e:
            return {"error": f"Failed to save todos: {e}"}

        pending = len([t for t in cleaned if t["status"] == "pending"])
        in_progress = len([t for t in cleaned if t["status"] == "in_progress"])
        completed = len([t for t in cleaned if t["status"] == "completed"])

        return {
            "saved": len(cleaned),
            "summary": {
                "pending": pending,
                "in_progress": in_progress,
                "completed": completed,
            },
        }


class PlanExitTool:
    name = "plan_exit"
    description = (
        "Exit plan mode and hand off the completed plan to the execution agent. "
        "Call this when you have finished writing the plan. "
        "Only available in plan agent type."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        plan = str(params.get("plan") or "").strip()
        summary = str(params.get("summary") or "").strip()
        if not plan:
            return {"error": "plan is required"}

        # Store plan in session metadata
        if context.db and context.session_id:
            try:
                result = await context.db.execute(select(Session).where(Session.id == context.session_id))
                session = result.scalar_one_or_none()
                if session:
                    metadata = dict(session.metadata_ or {})
                    metadata["plan"] = {"content": plan, "summary": summary, "status": "ready"}
                    session.metadata_ = metadata
                    await context.db.commit()
            except SQLAlchemyError:
                pass

        return {
            "status": "plan_ready",
            "summary": summary,
            "plan_length": len(plan),
            "message": "Plan saved. Execution agent will now proceed.",
        }
