"""Pre-persistence response guard orchestration for the standard loop."""

from __future__ import annotations

from typing import Any

from ....services.secure_work.coding.verification_contract import is_governed_coding_contract
from ....services.session.turn_execution_snapshot import AGENT_REPLY_CONTRACT_KEY
from ....services.workflow_routing.model_catalog import MODEL_WORKFLOW_CATALOG_PROMPT_MARKER
from ._loop_answer_evidence import handle_answer_evidence_guard
from ._loop_coding_guard_nudges import CodingGuardInputs
from ._loop_message_response_policy import build_tool_execution_status_message
from ._loop_reply_contract import handle_reply_contract_check
from ._loop_response_coding import handle_coding_response_guards
from ._loop_response_followup import handle_followup_response_guards
from ._loop_response_followup_inputs import FollowupGuardInputs
from ._loop_response_guard_inputs import ResponseGuardInputs
from ._loop_response_preguards import context_sub_agent_depth, governed_coding_awaits_delivery, handle_pre_guards
from ._loop_response_transition_inputs import TransitionGuardInputs
from ._loop_response_transitions import handle_transition_response_guards
from ._loop_workflow_checks import handle_workflow_checks_guard, phase_tool_evidence_present, record_if_turn_ended

# First line of the model-side workflow catalog prompt section
# ("## Workflow catalog"). Literal marker, not a heuristic: when this section
# is in the turn's system prompt, `select_workflow` is callable even with zero
# native tool definitions (MiniMax-style runtimes call it inline-textually via
# the repair layer), so a transitional announcement must be nudged, not
# accepted as final.
_WORKFLOW_CATALOG_PROMPT_MARKER = MODEL_WORKFLOW_CATALOG_PROMPT_MARKER
_NON_PROGRESS = "consecutive_non_progress_response_count"
_TRANSITIONAL = "consecutive_transitional_response_count"
_CODING_NO_EXECUTION = "consecutive_coding_no_execution_count"


def _workflow_catalog_prompted(context_snapshot: dict[str, Any] | None) -> bool:
    snapshot = context_snapshot if isinstance(context_snapshot, dict) else {}
    return _WORKFLOW_CATALOG_PROMPT_MARKER in str(snapshot.get("system_prompt") or "")


def _visible_tool_names(tool_calls: list[dict[str, Any]] | None) -> list[str]:
    names: list[str] = []
    for tool_call in tool_calls or []:
        function = tool_call.get("function") if isinstance(tool_call, dict) else {}
        tool_name = str((function or {}).get("name") or "").strip()
        if not tool_name or tool_name in {"load_tool_artifact", "release_context"}:
            continue
        if tool_name not in names:
            names.append(tool_name)
    return names


async def _transition_guard(inputs: ResponseGuardInputs, *, workflow_id: str, has_contract: bool) -> dict[str, Any]:
    transition_tools_available = (
        bool(inputs.current_tool_definitions)
        or bool(has_contract and inputs.turn_tool_history)
        or _workflow_catalog_prompted(inputs.context_snapshot)
    )
    is_transitional = inputs.is_transitional_assistant_response
    return await handle_transition_response_guards(TransitionGuardInputs(
        db=inputs.db, session_id=inputs.session_id, runtime=inputs.runtime, response=inputs.response,
        request_messages=inputs.request_messages, messages=inputs.messages, context_snapshot=inputs.context_snapshot,
        runtime_attempts=inputs.runtime_attempts, runtime_settings=inputs.runtime_settings,
        usage_model=inputs.usage_model,
        content=inputs.content,
        tool_calls=inputs.tool_calls,
        current_tool_definitions=inputs.current_tool_definitions,
        current_step=inputs.current_step,
        has_followup_steps=inputs.has_followup_steps(),
        turn_tool_history=inputs.turn_tool_history,
        consecutive_non_progress_response_count=inputs.consecutive_non_progress_response_count,
        consecutive_transitional_response_count=inputs.consecutive_transitional_response_count,
        is_transitional_assistant_response=(
            lambda text, calls, _tools_available: is_transitional(text, calls, transition_tools_available)
        ),
        is_non_substantive_assistant_response=inputs.is_non_substantive_assistant_response,
        looks_like_step_completion_summary=inputs.looks_like_step_completion_summary,
        build_stalled_step_message=inputs.build_stalled_step_message,
        persist_suppressed_runtime_response=inputs.persist_suppressed_runtime_response,
        persist_turn_trace=inputs.persist_turn_trace,
        persist_traced_assistant_message=inputs.persist_traced_assistant_message,
        workflow_id=workflow_id,
        request_analysis=inputs.request_analysis,
    ))


async def _coding_guard(inputs: ResponseGuardInputs, *, has_contract: bool) -> dict[str, Any]:
    tool_calls, turn_tool_history = inputs.tool_calls, inputs.turn_tool_history
    return await handle_coding_response_guards(CodingGuardInputs(
        db=inputs.db, session_id=inputs.session_id, runtime=inputs.runtime, response=inputs.response,
        request_messages=inputs.request_messages, messages=inputs.messages, context_snapshot=inputs.context_snapshot,
        runtime_attempts=inputs.runtime_attempts, runtime_settings=inputs.runtime_settings,
        usage_model=inputs.usage_model,
        content=inputs.content,
        tool_calls=tool_calls,
        current_step=inputs.current_step,
        current_step_index=inputs.current_step_index,
        current_step_iterations=inputs.current_step_iterations,
        current_step_max_iterations=inputs.current_step_max_iterations,
        current_step_tool_activity=inputs.current_step_tool_activity,
        active_steps=inputs.active_steps,
        workflow_artifact_ready_for_final_response=has_contract
        and inputs.workflow_artifact_contract_satisfied(inputs.workflow_contract, turn_tool_history=turn_tool_history),
        current_turn_content=inputs.current_turn_content,
        capability_type=inputs.capability_type,
        tool_context=inputs.tool_context,
        turn_tool_history=turn_tool_history,
        consecutive_non_progress_response_count=inputs.consecutive_non_progress_response_count,
        consecutive_transitional_response_count=inputs.consecutive_transitional_response_count,
        consecutive_coding_no_execution_count=inputs.consecutive_coding_no_execution_count,
        allows_noop_step_completion=inputs.allows_noop_step_completion,
        build_required_tool_reminder=inputs.build_required_tool_reminder,
        build_stalled_step_message=inputs.build_stalled_step_message,
        persist_suppressed_runtime_response=inputs.persist_suppressed_runtime_response,
        persist_turn_trace=inputs.persist_turn_trace,
        persist_traced_assistant_message=inputs.persist_traced_assistant_message,
        _has_meaningful_coding_execution=inputs._has_meaningful_coding_execution,
        _is_probable_coding_change_request=inputs._is_probable_coding_change_request,
        _looks_like_coding_intent_only_response=inputs._looks_like_coding_intent_only_response,
        phase_tool_evidence_present=not tool_calls and await phase_tool_evidence_present(
            inputs.db, inputs.session_id, request_analysis=inputs.request_analysis, turn_tool_history=turn_tool_history
        ),
        governed_coding=is_governed_coding_contract(inputs.workflow_contract),
    ))


async def _followup_guard(inputs: ResponseGuardInputs, *, workflow_id: str) -> dict[str, Any]:
    return await handle_followup_response_guards(FollowupGuardInputs(
        db=inputs.db, session_id=inputs.session_id, runtime=inputs.runtime, response=inputs.response,
        request_messages=inputs.request_messages, messages=inputs.messages, context_snapshot=inputs.context_snapshot,
        runtime_attempts=inputs.runtime_attempts, runtime_settings=inputs.runtime_settings,
        usage_model=inputs.usage_model,
        content=inputs.content,
        tool_calls=inputs.tool_calls,
        current_step=inputs.current_step,
        current_turn_content=inputs.current_turn_content,
        request_analysis=inputs.request_analysis,
        context_plan=inputs.context_plan,
        turn_tool_history=inputs.turn_tool_history,
        step_tool_history=inputs.step_tool_history,
        executed_tool_names=inputs.executed_tool_names,
        covered_evidence_axes=inputs.covered_evidence_axes,
        workflow_contract=inputs.workflow_contract,
        workflow_id=workflow_id,
        tdd_cycle_state=inputs.tdd_cycle_state,
        consecutive_non_progress_response_count=inputs.consecutive_non_progress_response_count,
        consecutive_coding_no_execution_count=inputs.consecutive_coding_no_execution_count,
        consecutive_transitional_response_count=inputs.consecutive_transitional_response_count,
        persist_suppressed_runtime_response=inputs.persist_suppressed_runtime_response,
        persist_traced_assistant_message=inputs.persist_traced_assistant_message,
        build_stalled_step_message=inputs.build_stalled_step_message,
        build_tdd_cycle_incomplete_reminder=inputs.build_tdd_cycle_incomplete_reminder,
        build_initial_tdd_cycle_state=inputs.build_initial_tdd_cycle_state,
        is_tdd_cycle_complete=inputs.is_tdd_cycle_complete,
        is_tdd_cycle_step=inputs.is_tdd_cycle_step,
        _is_self_review_step=inputs._is_self_review_step,
        _is_self_review_step_complete=inputs._is_self_review_step_complete,
        _build_incomplete_self_review_reminder=inputs._build_incomplete_self_review_reminder,
        workflow_artifact_contract_satisfied=inputs.workflow_artifact_contract_satisfied,
    ))


async def _delegated_guards(
    inputs: ResponseGuardInputs, ended_turn: dict[str, Any], *, workflow_id: str, has_contract: bool
) -> dict[str, Any] | None:
    """Transition, coding and follow-up guards in order; the first that ends or redirects the turn wins."""
    if not governed_coding_awaits_delivery(inputs):
        transition_outcome = await _transition_guard(inputs, workflow_id=workflow_id, has_contract=has_contract)
        if transition_outcome.get("action") != "none":
            await record_if_turn_ended(transition_outcome, **ended_turn)
            return transition_outcome
        inputs.take_counts(transition_outcome, _NON_PROGRESS, _TRANSITIONAL)
    coding_outcome = await _coding_guard(inputs, has_contract=has_contract)
    if coding_outcome.get("action") != "none":
        await record_if_turn_ended(coding_outcome, **ended_turn)
        return coding_outcome
    inputs.take_counts(coding_outcome, _NON_PROGRESS, _CODING_NO_EXECUTION)
    followup_outcome = await _followup_guard(inputs, workflow_id=workflow_id)
    if followup_outcome.get("action") != "none":
        await record_if_turn_ended(followup_outcome, **ended_turn)
        return followup_outcome
    inputs.take_counts(followup_outcome, _NON_PROGRESS, _CODING_NO_EXECUTION, _TRANSITIONAL)
    return None


async def _final_candidate_checks(
    inputs: ResponseGuardInputs, ended_turn: dict[str, Any], marked_content: dict[str, str]
) -> dict[str, Any] | None:
    """Answer evidence, reply contract and workflow checks on a candidate final reply."""
    db, session_id, response = inputs.db, inputs.session_id, inputs.response
    # A user-facing final answer cites this turn's tool evidence (uncited claims marked, never withheld).
    evidence_outcome = await handle_answer_evidence_guard(
        **inputs.turn_kwargs(), content=inputs.content, tool_calls=inputs.tool_calls,
        capability_type=inputs.capability_type, has_followup_steps=inputs.has_followup_steps(),
        sub_agent_depth=context_sub_agent_depth(inputs.context_snapshot), turn_tool_history=inputs.turn_tool_history,
        persist_turn_trace=inputs.persist_turn_trace,
        persist_traced_assistant_message=inputs.persist_traced_assistant_message,
    )
    if evidence_outcome is not None and evidence_outcome.get("action") == "mark":
        # The answer is delivered with its uncited claims marked; the later guards see the delivered text.
        inputs.content = str(evidence_outcome["content"])
        response["content"] = inputs.content
        marked_content["content"] = inputs.content
        evidence_outcome = None
    await record_if_turn_ended(evidence_outcome, **ended_turn)
    if evidence_outcome is not None:
        return {**evidence_outcome, **inputs.counts(non_progress_bump=1)}
    # The selected agent's checked reply format, once per candidate final (no retry, no repair).
    contract_outcome = await handle_reply_contract_check(
        db=db, session_id=session_id, runtime=inputs.runtime, response=response,
        request_messages=inputs.request_messages, context_snapshot=inputs.context_snapshot,
        runtime_attempts=inputs.runtime_attempts, runtime_settings=inputs.runtime_settings,
        usage_model=inputs.usage_model, content=inputs.content, tool_calls=inputs.tool_calls,
        has_followup_steps=inputs.has_followup_steps(),
        agent_definition=getattr(inputs.tool_context, "agent_definition", None),
        persist_traced_assistant_message=inputs.persist_traced_assistant_message,
    )
    await record_if_turn_ended(contract_outcome, **ended_turn)
    if contract_outcome is not None:
        return {**contract_outcome, **inputs.counts()}
    # A6: the selected workflow's blocking checks (one reminder, then accepted as not_verified).
    checks_outcome = await handle_workflow_checks_guard(
        **inputs.turn_kwargs(), content=inputs.content, tool_calls=inputs.tool_calls,
        has_followup_steps=inputs.has_followup_steps(),
        sub_agent_depth=context_sub_agent_depth(inputs.context_snapshot), request_analysis=inputs.request_analysis,
        turn_tool_history=inputs.turn_tool_history, persist_turn_trace=inputs.persist_turn_trace,
    )
    if checks_outcome is not None:
        return {**checks_outcome, **inputs.counts(non_progress_bump=1)}
    return None


def _persisted_assistant_content(inputs: ResponseGuardInputs, *, suppressed_tool_call_preamble: bool) -> str:
    content, tool_calls = inputs.content, inputs.tool_calls
    suppress_tool_call_preamble = inputs.is_transitional_tool_call_preamble(content, tool_calls)
    suppress_coding_tool_call_preamble = bool(tool_calls and inputs._looks_like_coding_intent_only_response(content))
    if tool_calls and (
        suppressed_tool_call_preamble or suppress_tool_call_preamble or suppress_coding_tool_call_preamble
    ):
        return build_tool_execution_status_message(tool_names=_visible_tool_names(tool_calls))
    if tool_calls and not str(content or "").strip():
        return build_tool_execution_status_message(tool_names=_visible_tool_names(tool_calls))
    return content


async def handle_response_guards(inputs: ResponseGuardInputs) -> dict[str, Any]:
    # A reply-contract record belongs only to the candidate the check below reads; a candidate a
    # guard ends earlier must not carry an earlier one's result on its trace.
    inputs.context_snapshot.pop(AGENT_REPLY_CONTRACT_KEY, None)
    workflow_id = str((inputs.workflow_contract or {}).get("workflow_id") or "").strip()
    has_contract = bool(inputs.workflow_contract and workflow_id)
    suppressed_tool_call_preamble = False
    if inputs.tool_calls and (
        inputs.is_transitional_tool_call_preamble(inputs.content, inputs.tool_calls)
        or inputs._looks_like_coding_intent_only_response(inputs.content)
    ):
        suppressed_tool_call_preamble = True
        inputs.content = ""
    ended_turn = {"db": inputs.db, "session_id": inputs.session_id, "messages": inputs.messages,
                  "context_snapshot": inputs.context_snapshot, "content": inputs.content,
                  "request_analysis": inputs.request_analysis, "turn_tool_history": inputs.turn_tool_history,
                  "sub_agent_depth": context_sub_agent_depth(inputs.context_snapshot)}
    outcome = await handle_pre_guards(inputs, workflow_id=workflow_id, has_active_workflow_contract=has_contract)
    if outcome is None:
        outcome = await _delegated_guards(inputs, ended_turn, workflow_id=workflow_id, has_contract=has_contract)
    marked_content: dict[str, str] = {}
    if outcome is None:
        outcome = await _final_candidate_checks(inputs, ended_turn, marked_content)
    if outcome is not None:
        return outcome
    persisted = _persisted_assistant_content(inputs, suppressed_tool_call_preamble=suppressed_tool_call_preamble)
    return {"action": "none", **marked_content, "persisted_assistant_content": persisted, **inputs.counts()}
