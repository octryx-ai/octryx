"""A reply that writes tool calls as text is never the turn's answer.

A turn offered zero tools can still get a reply with ````tool_use`` fences naming tools that do
not exist (``jira_search_issues``, ``jira_get_project_versions``). Nothing executes, so that text
must not go out as the final answer.

The provider-level inline recovery (``agent/providers/inline_tool_calls``) turns
recognisable inline calls into tool calls, and the loop's text-derived call audit
(``agent/loops/runtime/_loop_textual_tool_repair``) rejects the ones naming unknown or
unauthorised tools. This guard closes what is left: a reply without an executable tool
call that still carries an inline call (by the structural grammars of
:func:`pseudo_tool_call_names`), or whose text-derived calls the audit rejected.

- The retry budget (the loop's transition limit) is not spent: the reply is suppressed and
  the model is reminded that text is never executed. A turn with zero native tools still
  gets the reminder: catalog-prompted runtimes call ``select_workflow`` inline, and the
  repair layer executes such a call when it is authorised.
- The model repeats it: the turn ends in the closed refusal ``inline_pseudo_tool_call``
  (``raw_output.refusal_reason``) with an explicit message; the pseudo-call text is never
  delivered.

A structural check of the reply's shape against the known inline-call grammars only; the
meaning of the text is never guessed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from ....services.prompt_catalog import render_prompt
from ...providers.inline_tool_calls import pseudo_tool_call_names

PSEUDO_TOOL_CALL_REFUSAL_REASON = "inline_pseudo_tool_call"
_MAX_REPORTED_NAMES = 5
_TOOL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")


def _rejected_text_derived_calls(context_snapshot: dict[str, Any]) -> list[str]:
    audit = context_snapshot.get("repaired_textual_tool_calls")
    if not isinstance(audit, dict) or audit.get("count"):
        return []
    return [str(item.get("tool_name") or "") for item in audit.get("rejected") or [] if isinstance(item, dict)]


def pseudo_tool_call_reply(
    content: str,
    tool_calls: list[dict[str, Any]] | None,
    context_snapshot: dict[str, Any] | None,
) -> list[str] | None:
    """The tool names a reply wrote as text (``""`` when unnamed), or ``None`` for a normal reply."""
    if tool_calls:
        return None
    snapshot = context_snapshot if isinstance(context_snapshot, dict) else {}
    names = [*pseudo_tool_call_names(content), *_rejected_text_derived_calls(snapshot)]
    return names or None


def _reported_names(names: list[str]) -> list[str]:
    return list(dict.fromkeys(name for name in names if _TOOL_NAME.match(name)))[:_MAX_REPORTED_NAMES]


def pseudo_tool_call_refusal_message(names: list[str], *, tools_offered: bool) -> str:
    named = _reported_names(names)
    written = f" ({', '.join(named)})" if named else ""
    cause = render_prompt(
        "loop.pseudo_tool_call.cause_tools_offered" if tools_offered else "loop.pseudo_tool_call.cause_no_tools"
    )
    return render_prompt("loop.pseudo_tool_call.refusal", written=written, cause=cause)


async def handle_pseudo_tool_call_reply(
    *,
    db: Any,
    session_id: str,
    runtime: dict[str, Any],
    response: dict[str, Any],
    request_messages: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    context_snapshot: dict[str, Any],
    runtime_attempts: list[dict[str, Any]],
    runtime_settings: dict[str, Any],
    usage_model: str,
    content: str,
    tool_calls: list[dict[str, Any]] | None,
    current_tool_definitions: list[dict[str, Any]],
    consecutive_non_progress_response_count: int,
    retry_limit: int,
    persist_turn_trace: Callable[..., Any],
    persist_traced_assistant_message: Callable[..., Any],
) -> dict[str, Any] | None:
    """Suppress or refuse a pseudo tool-call reply; ``None`` when the reply is not one."""
    names = pseudo_tool_call_reply(content, tool_calls, context_snapshot)
    if names is None:
        return None
    count = consecutive_non_progress_response_count + 1
    tools_offered = bool(current_tool_definitions)
    raw_output = {
        "content": content,
        "tool_calls": [],
        "runtime_attempts": runtime_attempts,
        "pseudo_tool_call_names": _reported_names(names),
        "offered_tool_count": len(current_tool_definitions or []),
    }
    usage = response.get("usage", {})
    if count < retry_limit:
        messages.append({"role": "assistant", "content": content or ""})
        messages.append({"role": "system", "content": render_prompt("loop.pseudo_tool_call.retry_reminder")})
        await persist_turn_trace(
            db=db, session_id=session_id, message_id=None, provider=runtime["provider_name"], model=usage_model,
            input_messages=request_messages, context_snapshot=context_snapshot, tool_trace=[], usage=usage,
            raw_output={**raw_output, "suppressed_as_pseudo_tool_call": True}, trace_limits=runtime_settings,
        )
        await db.commit()
        return {"action": "continue", "consecutive_non_progress_response_count": count}
    final_content = pseudo_tool_call_refusal_message(names, tools_offered=tools_offered)
    await _persist_pseudo_tool_call_refusal(
        db=db, session_id=session_id, runtime=runtime, request_messages=request_messages,
        context_snapshot=context_snapshot, runtime_settings=runtime_settings, usage_model=usage_model, usage=usage,
        raw_output=raw_output, final_content=final_content,
        persist_traced_assistant_message=persist_traced_assistant_message,
    )
    return {
        "action": "return",
        "yield_content": final_content,
        "yield_model": usage_model,
        "consecutive_non_progress_response_count": count,
    }


async def _persist_pseudo_tool_call_refusal(
    *,
    db: Any,
    session_id: str,
    runtime: dict[str, Any],
    request_messages: list[dict[str, Any]],
    context_snapshot: dict[str, Any],
    runtime_settings: dict[str, Any],
    usage_model: str,
    usage: dict[str, Any],
    raw_output: dict[str, Any],
    final_content: str,
    persist_traced_assistant_message: Callable[..., Any],
) -> None:
    await persist_traced_assistant_message(
        db=db,
        session_id=session_id,
        content=final_content,
        provider=runtime["provider_name"],
        model=usage_model,
        input_messages=request_messages,
        context_snapshot=context_snapshot,
        tool_trace=[],
        raw_output={**raw_output, "refusal_reason": PSEUDO_TOOL_CALL_REFUSAL_REASON},
        usage=usage,
        tokens_in=usage.get("prompt_tokens", 0),
        tokens_out=usage.get("completion_tokens", 0),
        trace_limits=runtime_settings,
    )
    await db.commit()


def pseudo_tool_call_retry_reminder() -> str:
    """The retry reminder, rendered from the turn's prompt catalog (``loop.pseudo_tool_call.retry_reminder``)."""
    return render_prompt("loop.pseudo_tool_call.retry_reminder")


reported_pseudo_tool_call_names = _reported_names

__all__ = [
    "PSEUDO_TOOL_CALL_REFUSAL_REASON",
    "pseudo_tool_call_retry_reminder",
    "handle_pseudo_tool_call_reply",
    "pseudo_tool_call_refusal_message",
    "pseudo_tool_call_reply",
    "reported_pseudo_tool_call_names",
]
