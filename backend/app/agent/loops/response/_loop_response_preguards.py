"""Response guards that run before the transition/coding/follow-up guards: contract and summary domains."""

from __future__ import annotations

import re
from typing import Any

from ....services.prompt_catalog import render_prompt
from ....services.secure_work.coding.verification_contract import is_governed_coding_contract
from ....services.system_config.constants import DEFAULT_SUMMARY_DOMAIN_SATISFYING_TOOLS
from ...core.guards.summary_domains import build_summary_domain_reminder, missing_summary_domains
from ._loop_message_dedupe import append_unique_assistant_context, append_unique_system_message
from ._loop_response_coding import (
    _has_governed_coding_delivery,
    _looks_like_explicit_coding_blocker_or_noop,
)
from ._loop_response_guard_inputs import ResponseGuardInputs

_WORKFLOW_META_FINAL_PREFIXES = (
    "i can finalize",
    "i can now finalize",
    "i'm ready to finalize",
    "i am ready to finalize",
    "ready to finalize",
    "i can provide the final",
)
_KNOWLEDGE_EVIDENCE_TOOLS = {
    "knowledge_search",
}


def _required_summary_domains_from_request(request_analysis: dict[str, Any] | None) -> set[str]:
    analysis = request_analysis if isinstance(request_analysis, dict) else {}
    raw_domains = analysis.get("required_domains")
    if not isinstance(raw_domains, list):
        return set()
    return {str(domain).strip() for domain in raw_domains if str(domain).strip()}


def _covered_summary_domains_from_history(turn_tool_history: list[dict[str, Any]]) -> set[str]:
    covered: set[str] = set()
    for item in turn_tool_history or []:
        if not isinstance(item, dict):
            continue
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        if result.get("error"):
            continue
        tool_name = str(item.get("tool_name") or "").strip()
        if not tool_name:
            continue
        for domain, tools in DEFAULT_SUMMARY_DOMAIN_SATISFYING_TOOLS.items():
            if tool_name in tools:
                covered.add(str(domain))
    return covered


def _has_successful_knowledge_evidence(turn_tool_history: list[dict[str, Any]]) -> bool:
    for item in turn_tool_history or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("tool_name") or "").strip() not in _KNOWLEDGE_EVIDENCE_TOOLS:
            continue
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        if result and not result.get("error"):
            return True
    return False


def _is_substantive_answer(content: str) -> bool:
    text = re.sub(r"\s+", " ", str(content or "")).strip()
    if len(text) < 80:
        return False
    return not text.lower().startswith(("i will", "i can", "i need to", "let me", "next", "now i"))


def context_sub_agent_depth(context_snapshot: dict[str, Any] | None) -> int:
    if not isinstance(context_snapshot, dict):
        return 0
    try:
        return max(0, int(context_snapshot.get("sub_agent_depth") or 0))
    except (TypeError, ValueError):
        return 0


def governed_coding_awaits_delivery(inputs: ResponseGuardInputs) -> bool:
    """A governed coding turn answering without tools, without delivery and without naming a blocker."""
    return (
        not inputs.tool_calls
        and is_governed_coding_contract(inputs.workflow_contract)
        and not _has_governed_coding_delivery(inputs.turn_tool_history)
        and not _looks_like_explicit_coding_blocker_or_noop(inputs.content)
    )


async def _suppress_and_continue(inputs: ResponseGuardInputs, raw_output: dict[str, Any]) -> dict[str, Any]:
    await inputs.persist_suppressed_runtime_response(
        db=inputs.db,
        session_id=inputs.session_id,
        provider=inputs.runtime["provider_name"],
        model=inputs.usage_model,
        request_messages=inputs.request_messages,
        context_snapshot=inputs.context_snapshot,
        response=inputs.response,
        raw_output=raw_output,
        trace_limits=inputs.runtime_settings,
    )
    await inputs.db.commit()
    return {"action": "continue", **inputs.counts(non_progress_bump=1)}


async def _workflow_contract_guard(inputs: ResponseGuardInputs, workflow_id: str) -> dict[str, Any] | None:
    """A satisfied workflow contract: no more tool calls, and no meta "I can finalize" reply."""
    content, tool_calls = inputs.content, inputs.tool_calls
    if tool_calls:
        inputs.messages.append({"role": "assistant", "content": content or ""})
        inputs.messages.append({"role": "system", "content": render_prompt("loop.contract_satisfied")})
        return await _suppress_and_continue(inputs, {
            "content": content,
            "tool_calls": tool_calls,
            "runtime_attempts": inputs.runtime_attempts,
            "suppressed_for_completed_workflow_contract": True,
            "workflow_id": workflow_id,
        })
    if not str(content or "").strip().lower().startswith(_WORKFLOW_META_FINAL_PREFIXES):
        return None
    inputs.messages.append({"role": "assistant", "content": content or ""})
    inputs.messages.append({"role": "system", "content": render_prompt("loop.meta_final_reply")})
    return await _suppress_and_continue(inputs, {
        "content": content,
        "tool_calls": [],
        "runtime_attempts": inputs.runtime_attempts,
        "suppressed_for_workflow_meta_final": True,
        "workflow_id": workflow_id,
    })


async def _summary_domain_guard(inputs: ResponseGuardInputs) -> dict[str, Any] | None:
    content, turn_tool_history = inputs.content, inputs.turn_tool_history
    missing_summary = missing_summary_domains(
        _required_summary_domains_from_request(inputs.request_analysis),
        _covered_summary_domains_from_history(turn_tool_history),
    )
    if not (
        missing_summary
        and not inputs.tool_calls
        and not governed_coding_awaits_delivery(inputs)
        and not (_has_successful_knowledge_evidence(turn_tool_history) and _is_substantive_answer(content))
    ):
        return None
    append_unique_assistant_context(inputs.messages, content or "")
    append_unique_system_message(inputs.messages, build_summary_domain_reminder(missing_summary))
    return await _suppress_and_continue(inputs, {
        "content": content,
        "tool_calls": [],
        "runtime_attempts": inputs.runtime_attempts,
        "suppressed_for_missing_summary_domains": missing_summary,
    })


async def handle_pre_guards(
    inputs: ResponseGuardInputs, *, workflow_id: str, has_active_workflow_contract: bool
) -> dict[str, Any] | None:
    """The first guard that suppresses the reply, or None when the reply passes all of them."""
    if has_active_workflow_contract and inputs.workflow_artifact_ready_for_final_response:
        outcome = await _workflow_contract_guard(inputs, workflow_id)
        if outcome is not None:
            return outcome
    return await _summary_domain_guard(inputs)


__all__ = ["context_sub_agent_depth", "governed_coding_awaits_delivery", "handle_pre_guards"]
