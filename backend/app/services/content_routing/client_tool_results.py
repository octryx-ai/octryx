"""Client tool results: the gateway's Workspace-policy check and the launcher's report of a finished tool."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..content_detection.examination import Examination
from ..content_security.handling import REASON_GATEWAY_REFUSED
from ..policy_engine.content_points import tool_result_query
from ..policy_engine.engine import PolicySetInvalidError, compile_policy_set, evaluate
from ..policy_engine.runtime import MODE_ENFORCE, current_runtime
from ..policy_engine.schema import CLIENT_TOOL_PREFIX, ORIGIN_CLIENT
from .conversation_state import CLAUDE_SESSION_HEADER, conversation_key
from .decision import REASON_CONTENT_POLICY_UNAVAILABLE
from .obligations import Unresolved, workspace_obligation
from .tool_results import check_tool_result

#: Claude Code names an MCP tool ``mcp__<server>__<tool>``: its output can be replaced by the launcher.
MCP_TOOL_PREFIX = "mcp__"


@dataclass(frozen=True, slots=True)
class ClientToolDenial:
    tool: str
    reason: str
    policies: tuple[str, ...] = ()
    obligation: str = ""


def client_tool_result_denial(results: Mapping[str, Examination], *, workspace_id: str,
                              principal: Any) -> ClientToolDenial | None:
    runtime = current_runtime()
    if runtime.mode != MODE_ENFORCE or not runtime.custom_text:
        return None
    for tool, live in results.items():
        query = tool_result_query(tool_name=f"{CLIENT_TOOL_PREFIX}{tool}", family=None, origin=ORIGIN_CLIENT,
                                  content=live.report.to_cedar(), workspace_id=workspace_id, principal=principal)
        try:
            evaluation = evaluate(compile_policy_set(query.policies + "\n" + runtime.custom_text), query.requests,
                                  query.entities)
        except PolicySetInvalidError:
            # Fail closed: an unanswerable engine must not let a finding through (clean results go on).
            if live.detected:
                return ClientToolDenial(tool, REASON_CONTENT_POLICY_UNAVAILABLE)
            continue
        if live.permits(evaluation.allowed and not evaluation.errors):
            continue
        resolved = workspace_obligation(evaluation.determining, tool_result=True)
        if isinstance(resolved, Unresolved):
            return ClientToolDenial(tool, resolved.reason, tuple(resolved.policies))
        return ClientToolDenial(tool, REASON_GATEWAY_REFUSED, tuple(resolved.policies), resolved.kind)
    return None


async def launcher_tool_result(hook_input: Mapping[str, Any], *, workspace_id: str, session_id: str,
                               principal: Any = None) -> dict[str, Any]:
    tool = str(hook_input.get("tool_name") or "")
    response = hook_input.get("tool_response")
    conversation = conversation_from_hook(hook_input)
    outcome = await check_tool_result(
        response, tool_name=f"{CLIENT_TOOL_PREFIX}{tool}", family=None, origin=ORIGIN_CLIENT,
        workspace_id=workspace_id, session_id=session_id, conversation=conversation, principal=principal,
        client_keeps=not tool.startswith(MCP_TOOL_PREFIX))  # the launcher replaces an MCP tool's output only
    if not outcome.notice:
        return {}
    found = ", ".join(f"{key} ×{count}" for key, count in dict(outcome.notice.get("found") or {}).items())
    if outcome.notice.get("kept_by_client"):  # a built-in tool: Claude Code keeps the output as it is
        return {**outcome.notice, "blocked": False,
                "notice": f"{found or 'content to check'} found by Octryx; Claude Code keeps this output and the "
                          "gateway checks it before a model reads it"}
    verb = "kept out of the model" if outcome.blocked else "masked"
    payload: dict[str, Any] = {**outcome.notice, "blocked": outcome.blocked,
                               "notice": f"{found or 'sensitive data'} {verb} by Octryx"}
    if outcome.notice.get("kind") == "withhold":
        payload["notice"] = f"{outcome.notice['withheld']} part(s) too large to check withheld by Octryx"
    if tool.startswith(MCP_TOOL_PREFIX) and not outcome.blocked:
        payload["updated_output"] = outcome.result
    return payload


def conversation_from_hook(hook_input: Mapping[str, Any]) -> str:
    return conversation_key({CLAUDE_SESSION_HEADER: str(hook_input.get("session_id") or "")})


__all__ = ["ClientToolDenial", "client_tool_result_denial", "conversation_from_hook", "launcher_tool_result"]
