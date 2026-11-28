"""Connector-backed helpers for scheduler step execution."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# The scheduler's connector steps run tools in this workspace root (default: the working directory).
CONNECTOR_STEP_WORKSPACE_ROOT_ENV = "OCTRYX_CONNECTOR_STEP_WORKSPACE_ROOT"


def _connector_step_workspace_root() -> Path:
    configured = str(os.environ.get(CONNECTOR_STEP_WORKSPACE_ROOT_ENV) or "").strip()
    root = (Path(configured).expanduser() if configured else Path.cwd()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


async def execute_connector_action(
    *,
    step: Any,
    context: dict[str, Any],
    db: Any,
    task: Any,
    task_run: Any,
    render_template_params: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    from app.tools.context import ToolContext

    from ...services.project import get_project_config
    from ...services.run_capability.schedule_capability import schedule_tool_context_capability
    from ...tools.registry import execute_tool

    # The step runs in the task's Workspace: the Workspace-scoped tools (knowledge_search) read it from here.
    project_config = {**await get_project_config(task.project_id, db),
                      **({"project_id": task.project_id} if task.project_id else {})}
    workspace_root = _connector_step_workspace_root()
    tool_ctx = ToolContext(
        user_id=task.owner_id,
        project_ids=[task.project_id] if task.project_id else [],
        roles=list(CONNECTOR_STEP_ROLES),
        session_id=task_run.id,
        project_config=project_config,
        db=db,
        workspace_root=str(workspace_root),
        run_capability=schedule_tool_context_capability(task),
    )
    params = render_template_params(dict(step.connector_params), context)
    return await execute_tool(step.connector_action, params, tool_ctx)


#: The roles a scheduled connector step runs with, fixed on the server. The task itself still runs as its owner
#: and under its declared capability.
CONNECTOR_STEP_ROLES = ("operator",)


def deduplicate_items(items: list[Any], task: Any) -> tuple[list[Any], dict[str, str]]:
    config = dict(task.config or {})
    items_state: dict[str, str] = dict(config.get("_items_state", {}))
    new_items: list[Any] = []
    state_update: dict[str, str] = {}

    for item in items:
        item_id = str(item.get("key") or item.get("id") or item.get("ticket_id") or id(item))
        updated_at = str(item.get("updated") or item.get("updated_at") or "")
        if items_state.get(item_id) != updated_at:
            new_items.append(item)
            state_update[item_id] = updated_at

    return new_items, state_update
