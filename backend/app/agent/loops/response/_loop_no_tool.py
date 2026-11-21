"""No-tool response handling for the standard agent loop."""

from __future__ import annotations

import re
from typing import Any

from app.services.workflow_contracts.registry import workflow_contract_from_request_analysis

from ....services.prompt_catalog import render_prompt
from ...core.guards.summary_domains import build_summary_domain_reminder, missing_summary_domains
from ...core.runtime.turn_execution_binding import mark_turn_runtime_finished
from ..control._loop_progress_quality import detect_unsupported_no_tool_progress_claim
from ..request._loop_preflight import _skip_missing_evidence_for_workflow
from ._loop_no_tool_inputs import NoToolResponseInputs, followup_text
from ._loop_no_tool_repeats import handle_repeated_no_tool_response
from ._loop_source_evidence_answer import _has_source_evidence_final_prompt, _sanitize_source_evidence_final_answer

_KNOWLEDGE_EVIDENCE_TOOLS = {
    "knowledge_search",
}


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


def _is_substantive_no_tool_answer(content: str) -> bool:
    text = re.sub(r"\s+", " ", str(content or "")).strip()
    if len(text) < 80:
        return False
    if re.match(r"(?i)^(?:i will|i can|i need to|let me|next|now i)\b", text):
        return False
    return True


def _sanitized_content(inputs: NoToolResponseInputs) -> str:
    """The reply, cleaned in place (message, response, trace) when it answers a source-evidence final prompt."""
    content = inputs.content
    if not _has_source_evidence_final_prompt(inputs.request_messages):
        return content
    sanitized_content = _sanitize_source_evidence_final_answer(content, request_messages=inputs.request_messages)
    if sanitized_content != content:
        content = sanitized_content
        inputs.assistant_msg.content = sanitized_content
        if isinstance(inputs.response, dict):
            inputs.response["content"] = sanitized_content
        turn_trace = inputs.turn_trace
        if turn_trace is not None and isinstance(getattr(turn_trace, "raw_output", None), dict):
            turn_trace.raw_output = {**turn_trace.raw_output, "content": sanitized_content}
    return content


async def _persist_thread_context(
    inputs: NoToolResponseInputs, *, assistant_content: str, context_snapshot: Any, raw_output: dict[str, Any]
) -> Any:
    return await inputs.persist_runtime_thread_context(
        db=inputs.db,
        session_id=inputs.session_id,
        message_id=inputs.assistant_msg.id,
        current_user_message=inputs.current_turn_content,
        assistant_content=assistant_content,
        context_snapshot=context_snapshot,
        tool_trace=[],
        raw_output=raw_output,
    )


async def _remind_with_event(
    inputs: NoToolResponseInputs, *, content: str, tracking: dict[str, Any], event_key: str, event: dict[str, Any]
) -> dict[str, Any]:
    """Keep the reply, record the guard event and hand its message to the next turn as a reminder."""
    reminder = followup_text(str(event.get("message") or ""))
    existing_thread_context = await _persist_thread_context(
        inputs,
        assistant_content=content or reminder,
        context_snapshot={**dict(inputs.context_snapshot or {}), event_key: event},
        raw_output={
            "content": content, "tool_calls": [], "runtime_attempts": inputs.runtime_attempts, event_key: event
        },
    )
    await inputs.db.commit()
    return {
        "action": "continue",
        "yield_content": content or reminder,
        "existing_thread_context": existing_thread_context,
        **tracking,
        "followup_system_message": reminder,
    }


async def _quality_reminder_outcome(
    inputs: NoToolResponseInputs, *, content: str, workflow_contract: Any, tracking: dict[str, Any]
) -> dict[str, Any] | None:
    from ._loop_mermaid_reminder import detect_mermaid_instead_of_artifact

    mermaid_event = detect_mermaid_instead_of_artifact(
        assistant_content=content,
        turn_tool_history=inputs.turn_tool_history,
        context_snapshot=inputs.context_snapshot,
    )
    if mermaid_event:
        return await _remind_with_event(
            inputs, content=content, tracking=tracking, event_key="mermaid_artifact_reminder", event=mermaid_event
        )
    from ....services.secure_work.coding.verification_contract import is_governed_coding_contract

    progress_quality_event = detect_unsupported_no_tool_progress_claim(
        assistant_content=content,
        history=inputs.turn_tool_history,
        # The explicit governed signal: the workflow contract carries the approved verification contract.
        is_governed=is_governed_coding_contract(workflow_contract),
    )
    if progress_quality_event:
        outcome = await _remind_with_event(
            inputs, content=content, tracking=tracking, event_key="progress_quality_event", event=progress_quality_event
        )
        return {**outcome, "progress_quality_event": progress_quality_event}
    return None


async def _step_advance_outcome(
    inputs: NoToolResponseInputs, *, content: str, existing_thread_context: Any, tracking: dict[str, Any]
) -> dict[str, Any]:
    # A no-tool "step complete" claim must not advance a tdd_cycle
    # step into delivery while the verification contract is unproven
    # (same rule as the delivery gate and the tool-call advance).
    from ....services.coding_delivery_gate import delivery_step_advance_blocked
    from ...core.guards.response_guards import get_step_allowed_tools, get_step_field

    current_step_index = inputs.current_step_index
    next_step = inputs.active_steps[current_step_index + 1]
    advance_blocked = await delivery_step_advance_blocked(
        inputs.db,
        session_id=inputs.session_id,
        source_step_type=str(get_step_field(inputs.current_step, "stepType", "step_type", "") or ""),
        target_allowed_tools={
            str(name or "").strip() for name in get_step_allowed_tools(next_step) if str(name or "").strip()
        },
    )
    if advance_blocked:
        return {
            "action": "continue",
            "yield_content": content,
            "existing_thread_context": existing_thread_context,
            **tracking,
            "followup_system_message": followup_text(render_prompt("loop.tdd.validation_contract_unproven")),
        }
    return {
        "action": "advance_step",
        "yield_content": content,
        "existing_thread_context": existing_thread_context,
        "current_step_index": current_step_index + 1,
        "current_step_iterations": 0,
        "current_step_tool_activity": False,
        "current_step_wrapup_forced": False,
        **tracking,
    }


async def _missing_domains_or_step_outcome(
    inputs: NoToolResponseInputs, *, content: str, missing_domains: list[str], tracking: dict[str, Any]
) -> dict[str, Any] | None:
    """Missing summary domains ask for more evidence; a finished non-final step advances."""
    reminder = build_summary_domain_reminder(missing_domains) if missing_domains else content
    followup_system_message = followup_text(reminder) if missing_domains else ""
    existing_thread_context = await _persist_thread_context(
        inputs,
        assistant_content=content or reminder,
        context_snapshot=inputs.context_snapshot,
        raw_output={"content": content, "tool_calls": [], "runtime_attempts": inputs.runtime_attempts},
    )
    await inputs.db.commit()
    if missing_domains:
        return {
            "action": "continue",
            "yield_content": content or reminder,
            "existing_thread_context": existing_thread_context,
            **tracking,
            "followup_system_message": followup_system_message,
        }
    if inputs.current_step and inputs.current_step_index < len(inputs.active_steps) - 1:
        return await _step_advance_outcome(
            inputs, content=content, existing_thread_context=existing_thread_context, tracking=tracking
        )
    return None


async def _accept_final_answer(
    inputs: NoToolResponseInputs, *, content: str, tracking: dict[str, Any]
) -> dict[str, Any]:
    summary_needed = inputs.history_count >= inputs.summarize_threshold
    existing_thread_context = await _persist_thread_context(
        inputs, assistant_content=content, context_snapshot=inputs.context_snapshot,
        raw_output={"content": content, "tool_calls": []},
    )
    # The only accepted normal completion of a no-tool answer: every guard passed.
    mark_turn_runtime_finished(inputs.turn_trace)
    await inputs.db.commit()
    return {
        "action": "return",
        "yield_content": content,
        "existing_thread_context": existing_thread_context,
        **tracking,
        "summary_needed": summary_needed,
    }


def _missing_domains(inputs: NoToolResponseInputs, content: str, workflow_contract: Any) -> list[str]:
    missing_domains = missing_summary_domains(inputs.required_domains, inputs.covered_summary_domains)
    turn_tool_history = inputs.turn_tool_history
    if _skip_missing_evidence_for_workflow(workflow_contract, turn_tool_history=turn_tool_history) or (
        _has_successful_knowledge_evidence(turn_tool_history) and _is_substantive_no_tool_answer(content)
    ):
        missing_domains = []
    return missing_domains


async def handle_no_tool_response(inputs: NoToolResponseInputs) -> dict[str, Any]:
    content = _sanitized_content(inputs)
    current_step = inputs.current_step
    no_tool_signature = inputs.assistant_no_tool_response_signature(content)
    no_tool_similarity = inputs.assistant_no_tool_response_similarity(
        inputs.last_no_tool_response_content, content or ""
    )
    repeated = bool(
        current_step
        and inputs.last_no_tool_response_step_index is not None
        and inputs.current_step_index != inputs.last_no_tool_response_step_index
        and inputs.looks_like_step_completion_summary(content or "")
        and no_tool_similarity >= 0.72
    )
    repeated_count = inputs.repeated_previous_step_summary_count + 1 if repeated else 0
    last_signature = inputs.last_no_tool_response_signature
    if repeated or (no_tool_signature and last_signature and no_tool_signature == last_signature):
        return await handle_repeated_no_tool_response(
            inputs, content=content, no_tool_signature=no_tool_signature, no_tool_similarity=no_tool_similarity,
            repeated=repeated, repeated_count=repeated_count,
        )
    tracking = {
        "duplicate_no_tool_response_count": 0,
        "repeated_previous_step_summary_count": repeated_count,
        "last_no_tool_response_signature": no_tool_signature or last_signature,
        "last_no_tool_response_content": content or inputs.last_no_tool_response_content,
        "last_no_tool_response_step_index": inputs.current_step_index if current_step is not None else None,
    }
    workflow_contract = workflow_contract_from_request_analysis(inputs.request_analysis)
    missing_domains = _missing_domains(inputs, content, workflow_contract)
    outcome = await _quality_reminder_outcome(
        inputs, content=content, workflow_contract=workflow_contract, tracking=tracking
    )
    if outcome is None and (missing_domains or current_step):
        outcome = await _missing_domains_or_step_outcome(
            inputs, content=content, missing_domains=missing_domains, tracking=tracking
        )
    return outcome if outcome is not None else await _accept_final_answer(inputs, content=content, tracking=tracking)
