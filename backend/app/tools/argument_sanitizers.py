"""Per-tool argument projections for anything that leaves the execution boundary.

A tool call's arguments are model-supplied, and the writers that record them —
the ``ToolCall`` row, the assistant ``Message``, the turn trace, the SSE runtime
event stream, the orchestrator's own persistence — all run *before* any
governance decision exists. The raw payload can therefore not be what they
store: for the governed MCP resource and prompt bridge it can carry a
credential-bearing URI or a prompt argument holding a token.

This module is the seam for that. It is a small dispatch table keyed by tool
name: a tool with a registered projection is recorded in its governed,
publishable form, and every other tool's arguments pass through unchanged, so
the cost of the rule is paid only by the surfaces that need it.

A projection is a *persistence* rule, not an execution rule. It never has to
keep the tool callable, and the governed MCP bridge does not depend on it for
safety: those tools take an opaque catalog identity rather than a URI, so there
is no raw-URI channel into dispatch to begin with (see
``services/mcp_resource_arguments``).
"""

from __future__ import annotations

import json
from typing import Any

from ..models.json_text import safe_json_dict


def publishable_tool_arguments(tool_name: str, arguments: Any) -> Any:
    """Return the form of these arguments a writer outside dispatch may keep."""
    # Imported lazily: the MCP argument rules pull in the redaction policy and the
    # resource identity vocabulary, whose import chains must not run while the
    # tool registry is being built.
    from ..services.mcp_resource_arguments import publishable_mcp_resource_arguments

    governed = publishable_mcp_resource_arguments(tool_name, arguments)
    return arguments if governed is None else governed


def publishable_tool_call_payloads(tool_calls: Any) -> Any:
    """Return provider tool-call payloads with every argument projection applied.

    Used where the *assistant message* is persisted: its ``function.arguments``
    is the model's own raw request and is written before the call is governed.
    """
    if not isinstance(tool_calls, list):
        return tool_calls
    projected: list[Any] = []
    for tool_call in tool_calls:
        function = tool_call.get("function") if isinstance(tool_call, dict) else None
        if not isinstance(function, dict):
            projected.append(tool_call)
            continue
        raw_arguments = function.get("arguments")
        parsed = safe_json_dict(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
        governed = publishable_tool_arguments(str(function.get("name") or ""), parsed)
        if governed is parsed:
            projected.append(tool_call)
            continue
        projected.append(
            {
                **tool_call,
                "function": {
                    **function,
                    "arguments": json.dumps(governed, ensure_ascii=False, default=str)
                    if isinstance(raw_arguments, str)
                    else governed,
                },
            }
        )
    return projected


__all__ = ["publishable_tool_arguments", "publishable_tool_call_payloads"]
