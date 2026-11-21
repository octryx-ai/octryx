"""Request message and context construction for a standard loop turn."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ....services.turn_tool_history import merge_tool_history_from_messages
from ..response._loop_message_dedupe import dedupe_runtime_control_messages
from ._loop_request_context_snapshot import build_request_context_snapshot
from ._loop_request_tool_plan import apply_tool_plan, apply_working_set, plan_request_forced_tool_calls
from ._loop_request_tool_surface import (
    RequestSurface,
    apply_artifact_ready_surface,
    apply_offer_limits,
    apply_step_tool_surface,
    tool_names_of,
)


@dataclass(kw_only=True)
class RuntimeMessagesInputs:
    """The inputs of ``prepare_runtime_messages``; unknown or missing names raise ``TypeError``."""

    runtime_target_id: str | None
    tool_definitions: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    summary_context_msgs: list[dict[str, Any]]
    history: list[dict[str, Any]]
    thinking_level: str | None
    system_prompt: str
    personality_prompt: str
    memory_prompt: str
    skills_prompt: str
    system_context: Any
    agent_definition: dict[str, Any] | None
    context_plan: Any
    request_analysis: dict[str, Any]
    tool_context: Any
    runtime_settings: dict[str, Any]
    capability_type: str
    current_turn_content: str
    active_steps: list[dict[str, Any]]
    current_step: dict[str, Any] | None
    current_step_for_runtime: dict[str, Any] | None
    current_step_index: int
    elastic_iteration: dict[str, Any]
    tdd_cycle_state: dict[str, Any] | None
    existing_thread_context: dict[str, Any] | None
    turn_diff_tracker: Any
    turn_tool_history: list[dict[str, Any]]
    covered_evidence_axes: set[str]
    workflow_contract: dict[str, Any] | None
    workflow_artifact_ready_for_final_response: bool
    workflow_final_answer_prompted: bool
    forced_tool_calls: list[dict[str, Any]] | None
    current_runtimes: list[dict[str, Any]]
    current_coding_discipline: str
    current_reasoning_stage: str
    current_reasoning_task_type: str
    current_subtask_role: str
    build_current_step_prompt: Callable[[dict, int, int, str | None], str]
    filter_tool_definitions: Callable[[list[dict], list[str] | None], list[dict]]
    build_turn_working_summary_message: Callable[..., dict[str, Any] | None]
    build_within_turn_working_set_messages: Callable[..., tuple[list[dict[str, Any]], dict[str, Any]]]
    plan_forced_tool_calls_for_turn: Callable[..., list[dict[str, Any]] | None]
    _plan_coding_preflight_tool_calls: Callable[..., list[dict[str, Any]] | None]
    _augment_step_allowed_tools_for_request_analysis: Callable[[set[str], dict[str, Any]], set[str]]
    _build_workflow_artifact_ready_message: Callable[[dict[str, Any] | None], str]
    _latest_successful_tool_result_from_history: Callable[[list[dict[str, Any]], str], dict[str, Any] | None]
    workflow_contract_from_request_analysis: Callable[[dict[str, Any]], dict[str, Any] | None]
    plan_next_workflow_tool_calls: Callable[..., list[dict[str, Any]]]


def prepare_runtime_messages(inputs: RuntimeMessagesInputs) -> dict[str, Any]:
    effective_workflow_contract = inputs.workflow_contract or inputs.workflow_contract_from_request_analysis(
        inputs.request_analysis
    )
    planning_tool_history = merge_tool_history_from_messages(inputs.turn_tool_history, inputs.messages)
    surface = RequestSurface(
        tool_definitions=inputs.tool_definitions,
        allowed_tool_names=tool_names_of(inputs.tool_definitions),
        request_messages=dedupe_runtime_control_messages(inputs.messages),
    )
    context_snapshot = build_request_context_snapshot(inputs, effective_workflow_contract)
    if inputs.current_step:
        apply_step_tool_surface(inputs, surface, planning_tool_history=planning_tool_history)
    workflow_final_answer_prompted = inputs.workflow_final_answer_prompted
    if inputs.workflow_artifact_ready_for_final_response:
        workflow_final_answer_prompted = apply_artifact_ready_surface(
            inputs,
            surface,
            effective_workflow_contract=effective_workflow_contract,
            workflow_final_answer_prompted=workflow_final_answer_prompted,
        )
    deferred_catalog, text_only_agent = apply_offer_limits(inputs, surface, context_snapshot)
    apply_tool_plan(
        inputs,
        surface,
        context_snapshot,
        effective_workflow_contract=effective_workflow_contract,
        deferred_catalog=deferred_catalog,
    )
    apply_working_set(inputs, surface, context_snapshot)
    forced_tool_calls = plan_request_forced_tool_calls(
        inputs,
        surface,
        context_snapshot,
        planning_tool_history=planning_tool_history,
        text_only_agent=text_only_agent,
    )
    return {
        "context_snapshot": context_snapshot,
        "current_allowed_tool_names": surface.allowed_tool_names,
        "current_tool_definitions": surface.tool_definitions,
        "forced_tool_calls": forced_tool_calls,
        "request_messages": surface.request_messages,
        "workflow_final_answer_prompted": workflow_final_answer_prompted,
    }
