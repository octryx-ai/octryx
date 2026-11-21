"""Interactive Python runtime tools."""

from __future__ import annotations

from typing import Any

from ..services.interactive_python import interactive_python_manager
from .context import ToolContext


def _python_session_id(context: ToolContext, params: dict[str, Any]) -> str | None:
    return str(params.get("python_session_id") or context.session_id or "").strip() or None


async def _execute_python_action(*, action: str, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    payload = dict(params)
    payload.pop("python_session_id", None)
    return await interactive_python_manager.execute(
        python_session_id=_python_session_id(context, params),
        workspace_root=context.workspace_root,
        db=context.db,
        project_config=context.project_config,
        action=action,
        params=payload,
    )


class PythonExecCodeTool:
    name = "python_exec_code"
    description = "Execute Python code inside a persistent interactive Python session."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_python_action(action="exec_code", params=params, context=context)


class PythonListVariablesTool:
    name = "python_list_variables"
    description = "List variables currently stored in the interactive Python session."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_python_action(action="list_variables", params=params, context=context)


class PythonCloseSessionTool:
    name = "python_close_session"
    description = "Close the current interactive Python session."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_python_action(action="close", params=params, context=context)
