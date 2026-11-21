"""Default chat selection: which agent the composer preselects for a project."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ...services.agent_mode import DEFAULT_AGENT_MODE_KEY
from ...services.workspace_composition import (
    derive_workspace_default_chat_selection,
    get_workspace_execution_view,
)
from ._routing_catalog import _list_chat_agent_catalog, _load_project_config, _preference_map, _preference_status

__all__ = [
    "_derive_chat_default_selection",
    "_resolve_project_default_chat_selection",
]


def _derive_chat_default_selection(*, agent_options: list[dict[str, Any]]) -> dict[str, str]:
    primary_agent = next((item for item in agent_options if item.get("isPrimary")), None)
    if primary_agent is not None:
        return {
            "selected_agent_id": str(primary_agent.get("id") or "").strip(),
            "selected_agent_name": str(primary_agent.get("name") or "").strip(),
            "selected_agent_type": str(primary_agent.get("agentType") or DEFAULT_AGENT_MODE_KEY).strip()
            or DEFAULT_AGENT_MODE_KEY,
        }

    return {
        "selected_agent_id": "",
        "selected_agent_name": "",
        "selected_agent_type": DEFAULT_AGENT_MODE_KEY,
    }


def _first_with_preference(
    items: list[dict[str, Any]], preferences: dict, *, item_key: str, status: str
) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in items
            if _preference_status(preferences, str(item.get(item_key) or "").strip()) == status
        ),
        None,
    )


async def _resolve_project_default_chat_selection(
    *,
    db: AsyncSession,
    user: User,
    project_id: str | None,
) -> dict[str, str]:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return _derive_chat_default_selection(agent_options=[])
    workspace_execution_view = await get_workspace_execution_view(
        db,
        workspace_id=normalized_project_id,
    )
    workspace_selection = derive_workspace_default_chat_selection(workspace_execution_view)
    if str(workspace_selection.get("selected_agent_id") or "").strip():
        return workspace_selection
    project_config = await _load_project_config(db, normalized_project_id)
    agent_preferences = _preference_map(project_config, "project_agent_preferences")
    agent_options, _agent_groups = await _list_chat_agent_catalog(
        db,
        user=user,
        project_id=normalized_project_id,
    )
    explicit_primary_agent = _first_with_preference(
        agent_options, agent_preferences, item_key="id", status="primary"
    )
    if explicit_primary_agent is not None:
        return _derive_chat_default_selection(agent_options=[explicit_primary_agent])

    return _derive_chat_default_selection(agent_options=[])
