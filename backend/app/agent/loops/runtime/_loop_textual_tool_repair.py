"""Repair and audit of tool calls a model emitted as text instead of the
native tool-call channel.

Two seams feed this module:

- ``repair_textual_tool_request`` converts the ``Tool request <name>: {...}``
  placeholder grammar into an internal tool call (loop-level recovery).
- ``audit_text_derived_tool_calls`` validates EVERY text-derived tool call —
  loop-level repairs and the provider-level inline recoveries
  (``inline_call_*`` ids from :mod:`app.agent.providers.inline_tool_calls`) —
  against the tool definitions, the capability type, and the turn's
  authorization set, and stamps the audited
  ``repaired_textual_tool_calls`` counter into the turn trace.

Execution always continues through the normal dispatch: gates, guards, and
approval policies are untouched. Text found in quoted/fenced material or
naming tools outside the turn's authorization set is never executed
(poisoning protection).
"""

from __future__ import annotations

import ast
import json
import re
import uuid
from typing import Any

from ....tools.definitions import get_all_definitions, is_tool_definition_available_for_agent_type
from ...core.runtime.trace_runtime import compact_trace_value

_TEXTUAL_TOOL_REQUEST_PATTERN = re.compile(
    r"\bTool request\s+(?P<tool_name>[A-Za-z_][\w.-]*)\s*:\s*(?P<arguments>.*)\s*$",
    re.IGNORECASE | re.DOTALL,
)

# Id prefixes marking a tool call recovered from assistant TEXT rather than the
# provider's native tool-call channel. "inline_call_" is stamped by
# app.agent.providers.inline_tool_calls; "textual-tool-request-" by
# repair_textual_tool_request below.
TEXT_DERIVED_TOOL_CALL_ID_PREFIXES = ("inline_call_", "textual-tool-request-")


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, list | tuple | set):
        return set()
    return {str(item or "").strip() for item in value if str(item or "").strip()}


def _parse_textual_tool_arguments(raw_arguments: str) -> dict[str, Any]:
    arguments = str(raw_arguments or "").strip()
    if not arguments:
        return {}
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(arguments)
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _authorized_textual_tool_request_names(
    *,
    context_snapshot: dict[str, Any],
    current_allowed_tool_names: set[str],
    capability_type: str,
) -> set[str]:
    allowed = {str(name or "").strip() for name in current_allowed_tool_names if str(name or "").strip()}
    context_plan = context_snapshot.get("context_plan") if isinstance(context_snapshot.get("context_plan"), dict) else {}
    allowed.update(_string_set(context_plan.get("tool_allowlist")))

    catalog = (
        context_snapshot.get("session_tool_catalog")
        if isinstance(context_snapshot.get("session_tool_catalog"), dict)
        else {}
    )
    allowed.update(_string_set(catalog.get("policy_allowlist")))
    for entry in catalog.get("entries") or []:
        if isinstance(entry, dict):
            name = str(entry.get("name") or "").strip()
            if name:
                allowed.add(name)

    request_analysis = (
        context_snapshot.get("request_analysis")
        if isinstance(context_snapshot.get("request_analysis"), dict)
        else {}
    )
    workflow_contract = (
        request_analysis.get("workflow_contract")
        if isinstance(request_analysis.get("workflow_contract"), dict)
        else {}
    )
    allowed.update(_string_set(workflow_contract.get("allowed_tools")))

    definitions = get_all_definitions()
    return {
        name
        for name in allowed
        if name in definitions and is_tool_definition_available_for_agent_type(name, capability_type)
    }


def repair_textual_tool_request(
    *,
    content: str,
    tool_calls: list[dict[str, Any]] | None,
    context_snapshot: dict[str, Any],
    current_allowed_tool_names: set[str],
    capability_type: str,
) -> list[dict[str, Any]] | None:
    """Convert provider textual tool placeholders into audited internal tool calls."""

    if tool_calls:
        return None
    match = _TEXTUAL_TOOL_REQUEST_PATTERN.search(str(content or "").strip())
    if match is None:
        return None
    tool_name = str(match.group("tool_name") or "").strip()
    if not tool_name:
        return None
    authorized_names = _authorized_textual_tool_request_names(
        context_snapshot=context_snapshot,
        current_allowed_tool_names=current_allowed_tool_names,
        capability_type=capability_type,
    )
    if tool_name not in authorized_names:
        return None
    arguments = _parse_textual_tool_arguments(match.group("arguments") or "")
    current_allowed_tool_names.add(tool_name)
    context_snapshot["textual_tool_request_repair"] = compact_trace_value(
        {
            "status": "repaired",
            "tool_name": tool_name,
            "authorization_source": "routing_or_context_policy",
        },
        trace_limits={},
    )
    return [
        {
            "id": f"textual-tool-request-{uuid.uuid4()}",
            "type": "function",
            "function": {
                "name": tool_name,
                "arguments": json.dumps(arguments, ensure_ascii=False),
            },
        }
    ]


def _is_text_derived_tool_call(call: Any) -> bool:
    if not isinstance(call, dict):
        return False
    call_id = str(call.get("id") or "")
    return call_id.startswith(TEXT_DERIVED_TOOL_CALL_ID_PREFIXES)


def _text_derived_call_rejection(
    call: dict[str, Any],
    *,
    authorized_names: set[str],
    capability_type: str,
    definitions: dict[str, Any],
) -> str | None:
    """Return the rejection reason for a text-derived call, or None if valid."""
    function = call.get("function") if isinstance(call.get("function"), dict) else {}
    name = str(function.get("name") or "").strip()
    if not name:
        return "missing_tool_name"
    if name not in definitions:
        return "unknown_tool"
    if not is_tool_definition_available_for_agent_type(name, capability_type):
        return "tool_unavailable_for_capability"
    if authorized_names and name not in authorized_names:
        return "outside_turn_authorization"
    raw_arguments = function.get("arguments")
    if raw_arguments in (None, ""):
        return None
    try:
        parsed = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
    except json.JSONDecodeError:
        return "arguments_not_json"
    if not isinstance(parsed, dict):
        return "arguments_not_object"
    return None


def _offered_tool_names(offered_tool_definitions: list[dict[str, Any]] | None) -> set[str]:
    names: set[str] = set()
    for definition in offered_tool_definitions or []:
        if not isinstance(definition, dict):
            continue
        function = definition.get("function") if isinstance(definition.get("function"), dict) else {}
        name = str(function.get("name") or "").strip()
        if name:
            names.add(name)
    return names


def audit_text_derived_tool_calls(
    *,
    tool_calls: list[dict[str, Any]] | None,
    context_snapshot: dict[str, Any],
    current_allowed_tool_names: set[str],
    capability_type: str,
    offered_tool_definitions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]] | None:
    """Validate text-derived tool calls and stamp the audited counter.

    Returns the filtered tool-call list when any text-derived call was present
    (possibly empty when all were rejected), or ``None`` when the turn carried
    no text-derived calls (native channel — nothing to audit).

    The authorization set is the union of the turn's policy/contract/catalog
    allowlists and the tool definitions actually OFFERED to the model this
    turn — a tool the platform put in front of the model is executable, a tool
    name that only appears in quoted text is not.
    """
    calls = [call for call in (tool_calls or []) if isinstance(call, dict)]
    if not any(_is_text_derived_tool_call(call) for call in calls):
        return None

    authorized_names = _authorized_textual_tool_request_names(
        context_snapshot=context_snapshot,
        current_allowed_tool_names=current_allowed_tool_names,
        capability_type=capability_type,
    )
    authorized_names.update(_offered_tool_names(offered_tool_definitions))
    definitions = get_all_definitions()
    kept: list[dict[str, Any]] = []
    repaired_names: list[str] = []
    rejected: list[dict[str, str]] = []
    for call in calls:
        if not _is_text_derived_tool_call(call):
            kept.append(call)
            continue
        reason = _text_derived_call_rejection(
            call,
            authorized_names=authorized_names,
            capability_type=capability_type,
            definitions=definitions,
        )
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        name = str(function.get("name") or "").strip()
        if reason is None:
            kept.append(call)
            repaired_names.append(name)
        else:
            rejected.append({"tool_name": name, "reason": reason})

    context_snapshot["repaired_textual_tool_calls"] = compact_trace_value(
        {
            "count": len(repaired_names),
            "tool_names": repaired_names,
            "rejected": rejected,
        },
        trace_limits={},
    )
    return kept
