"""One governed tool dispatch of a governed agent run."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ...tools.context import ToolContext
from ...tools.definitions import get_tool_definition_metadata
from ...tools.registry import TOOL_REGISTRY, execute_tool
from ..tool_approval.rules import tool_approval_requirement
from .refusals import denied, failed, needs_configuration

_APPROVAL_REQUIRED = "approval_required"
_DENIED_BY_POLICY = "denied_by_policy"
_UNKNOWN_TOOL = "unknown_tool"


def tool_requires_approval(tool_name: str, project_config: Mapping[str, Any] | None) -> bool:
    if get_tool_definition_metadata(tool_name).approval_required:
        return True
    return tool_approval_requirement(tool_name, dict(project_config or {})).required


def is_registered_tool(tool_name: str) -> bool:
    return tool_name in TOOL_REGISTRY


def _json_safe(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(json.dumps(payload, default=str, allow_nan=False))
    except ValueError as exc:
        raise failed("tool_execution_failed") from exc


def raise_for_tool_execution(payload: Mapping[str, Any], *, execution_errors: bool = True) -> None:
    execution = payload.get("tool_execution")
    if not isinstance(execution, Mapping):
        return
    status = execution.get("status")
    category = execution.get("category")
    if status == _APPROVAL_REQUIRED or (status == "error" and category == _APPROVAL_REQUIRED):
        raise denied("tool_requires_approval")
    if status != "error":
        return
    if category == _DENIED_BY_POLICY:
        raise denied("tool_denied_by_policy")
    if category == _UNKNOWN_TOOL:
        raise needs_configuration("tool_unavailable")
    if execution_errors:
        raise failed("tool_execution_failed")


async def governed_tool_payload(
    tool_name: str, arguments: dict[str, Any], context: ToolContext, *, execution_errors: bool = True
) -> dict[str, Any]:
    if not is_registered_tool(tool_name):
        raise needs_configuration("tool_unavailable")
    if tool_requires_approval(tool_name, context.project_config):
        raise denied("tool_requires_approval")
    payload = await execute_tool(tool_name, arguments, context)
    if not isinstance(payload, dict):
        raise failed("tool_execution_failed")
    raise_for_tool_execution(payload, execution_errors=execution_errors)
    return _json_safe(payload)


__all__ = ["governed_tool_payload", "is_registered_tool", "raise_for_tool_execution", "tool_requires_approval"]
