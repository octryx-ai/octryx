"""Control plane and agent definition helpers."""

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import (
    AgentDefinition,
    Project,
    SavedPythonScript,
    User,
)
from ...services.agent_visibility import visible_agent_clause
from ...services.script import list_saved_scripts
from ...services.secret import secret_ref_label
from ...services.tool_config import (
    TOOL_CONFIG_PRESETS,
    build_tool_config_forms,
    list_tool_configs,
)

__all__ = [
    "_build_tools_context",
    "_list_agent_definitions",
]


def _tool_registry():
    from ...tools.registry import TOOL_REGISTRY

    return TOOL_REGISTRY


async def _build_tools_context(
    request: Request,
    db: AsyncSession,
    *,
    user: User,
    script_id: str | None = None,
    project_id: str = "",
    tool_test_results: dict[str, dict] | None = None,
) -> dict:
    scripts = await list_saved_scripts(db, active_only=False)
    editing_script = await db.get(SavedPythonScript, script_id) if script_id else None
    projects = (await db.execute(select(Project).order_by(Project.name.asc()))).scalars().all()
    tool_config_entries = await list_tool_configs(db, project_id or None)
    tool_config_forms = build_tool_config_forms(tool_config_entries, project_id or None, tool_test_results)
    for form in tool_config_forms:
        form["secret_ref_labels"] = {
            field_name: secret_ref_label(secret_id) for field_name, secret_id in form.get("secret_refs", {}).items()
        }
    built_in_tools = sorted(
        [{"name": tool.name, "description": getattr(tool, "description", "")} for tool in _tool_registry().values()],
        key=lambda item: item["name"],
    )
    return {
        "request": request,
        "user": user,
        "scripts": scripts,
        "editing_script": editing_script,
        "built_in_tools": built_in_tools,
        "projects": projects,
        "selected_project_id": project_id,
        "tool_config_forms": tool_config_forms,
        "tool_config_presets": TOOL_CONFIG_PRESETS,
    }


async def _list_agent_definitions(db: AsyncSession, *, user_id: str) -> list[AgentDefinition]:
    result = await db.execute(
        select(AgentDefinition)
        .options(selectinload(AgentDefinition.steps), selectinload(AgentDefinition.group))
        .where(await visible_agent_clause(db, user_id))
        .order_by(AgentDefinition.updated_at.desc(), AgentDefinition.name.asc())
    )
    return result.scalars().unique().all()


# The chat runtime options are owned by ``app.services.runtime_options`` (turn preparation reads them too); the
# web helpers and panel routers read them under this name.

# The agent payload builders are owned by ``app.services.agent_definition_payload``; the panel routers and admin
# contexts read them under these names (``app.web._serialize_agent_definition``).
