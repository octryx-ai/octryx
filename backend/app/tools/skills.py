"""Runtime skill discovery tools."""

from __future__ import annotations

from typing import Any

from ..services.skill_discovery_service import SkillAccessContext, get_skill_content, search_skills
from .context import ToolContext


class SkillSearchTool:
    name = "skill_search"
    description = "Search the published skill catalog and return compact metadata only."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "Database session is required"}
        return await search_skills(
            context.db,
            query=str(params.get("query") or context.current_user_message or ""),
            category=_optional_text(params.get("category")),
            source=_optional_text(params.get("source")),
            limit=params.get("limit") or 8,
            access_context=_access_context(context, params),
        )

    def is_read_only(self) -> bool:
        return True

    def is_concurrency_safe(self) -> bool:
        return True


class SkillGetTool:
    name = "skill_get"
    description = "Load one content level (or one reference file) of a published catalog skill."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "Database session is required"}
        return await get_skill_content(
            context.db,
            skill_id=_optional_text(params.get("skill_id") or params.get("id")),
            name=_optional_text(params.get("name")),
            content_level=str(params.get("content_level") or "summary"),
            access_context=_access_context(context, params),
            resource=_optional_text(params.get("resource")),
        )

    def is_read_only(self) -> bool:
        return True

    def is_concurrency_safe(self) -> bool:
        return True


def _access_context(context: ToolContext, params: dict) -> SkillAccessContext:
    project_id = _optional_text(params.get("project_id")) or _context_project_id(context)
    diagnostics = str(params.get("diagnostics") or "").strip().lower() in {"1", "true", "yes", "diagnostics"}
    return SkillAccessContext(
        user_roles=list(context.roles or []),
        user_id=context.user_id,
        session_id=context.session_id,
        project_id=project_id,
        agent_definition=context.agent_definition,
        request_id=context.request_id,
        available_tool_names=_available_tool_names(context),
        diagnostics=diagnostics,
    )


def _context_project_id(context: ToolContext) -> str | None:
    configured_project_id = _optional_text((context.project_config or {}).get("project_id"))
    if configured_project_id:
        return configured_project_id
    project_ids = [str(item or "").strip() for item in (context.project_ids or []) if str(item or "").strip()]
    return project_ids[0] if len(project_ids) == 1 else None


def _available_tool_names(context: ToolContext) -> set[str] | None:
    snapshot = context.turn_context_snapshot if isinstance(context.turn_context_snapshot, dict) else {}
    raw = snapshot.get("tool_names") or snapshot.get("available_tools")
    if not isinstance(raw, list):
        return None
    return {str(item or "").strip() for item in raw if str(item or "").strip()}


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


__all__ = ["SkillSearchTool", "SkillGetTool"]
