"""One governed tool dispatch of a governed agent run.

Every call goes through the registry's governance chain (``tools/registry.execute_tool``:
connector activation, project tool policy, run capability, MCP server and capability
policy, MCP resource policy, ``services/tool_approval_gate.py``, coding gates). Nothing
here executes a tool around it.

Approval semantics. A governed run never lets a tool wait for, or silently skip, an
approval: it has no one to ask. So before dispatch, a tool whose definition declares
``approval_required`` or that the project ``approval_policy`` covers ends the run
``denied`` / ``tool_requires_approval`` with zero executions and without creating an
approval request. A requirement that only the dispatch chain can
see (an MCP capability subject behind the bridge tool) is enforced by the chain; its
``approval_required`` result maps to the same ``denied`` outcome, and the tool body
did not run.

Result mapping (the registry's typed ``tool_execution`` metadata, never message text):

* ``approval_required``                     -> denied / ``tool_requires_approval``
* ``denied_by_policy``                      -> denied / ``tool_denied_by_policy``
* ``unknown_tool`` (or not registered)      -> needs_configuration / ``tool_unavailable``
* any other error category                  -> failed / ``tool_execution_failed``
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ...tools.context import ToolContext
from ...tools.definitions import get_tool_definition_metadata
from ...tools.registry import TOOL_REGISTRY, execute_tool
from ..tool_approval_rules import tool_approval_requirement
from .refusals import denied, failed, needs_configuration

_APPROVAL_REQUIRED = "approval_required"
_DENIED_BY_POLICY = "denied_by_policy"
_UNKNOWN_TOOL = "unknown_tool"


def tool_requires_approval(tool_name: str, project_config: Mapping[str, Any] | None) -> bool:
    """Whether dispatching *tool_name* would need an approval under its definition or the project policy."""
    if get_tool_definition_metadata(tool_name).approval_required:
        return True
    return tool_approval_requirement(tool_name, dict(project_config or {})).required


def is_registered_tool(tool_name: str) -> bool:
    return tool_name in TOOL_REGISTRY


def _json_safe(payload: dict[str, Any]) -> dict[str, Any]:
    """Tool payloads may carry non-JSON scalars (timestamps); they are recorded as strings."""
    try:
        return json.loads(json.dumps(payload, default=str, allow_nan=False))
    except ValueError as exc:
        raise failed("tool_execution_failed") from exc


def raise_for_tool_execution(payload: Mapping[str, Any], *, execution_errors: bool = True) -> None:
    """Refuse the run for a governed refusal; ``execution_errors=False`` leaves tool errors to the caller."""
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
    """Run exactly one governed tool call and return its JSON-safe payload, or refuse the run.

    With ``execution_errors=False`` (an agent's tool call) an ordinary tool error is returned
    as the payload, so the agent can react to it; governed refusals still end the run.
    """
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
