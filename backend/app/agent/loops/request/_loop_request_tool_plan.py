"""Tool catalog, tool plan, execution control, working set and forced calls of a standard loop request."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ....services.chat_deferred_tools import drop_unused_prompt_sections
from ....services.instructions.resolve import INSTRUCTIONS_METADATA_KEY
from ....services.secure_work.coding.verification_contract import is_governed_coding_contract
from ....services.tool_catalog import resolve_session_tool_catalog
from ....services.tool_planning import (
    build_tool_execution_control_contract,
    build_tool_plan_prompt_packet,
    build_trace_only_tool_plan_contract,
    filter_tool_definitions_for_execution_control,
)
from ...core.runtime.trace_runtime import compact_trace_value
from ...core.turn.decision_timeline import (
    append_context_prepared_event,
    append_forced_tool_plan_event,
    append_instructions_event,
    append_tool_catalog_event,
    append_tool_execution_control_event,
    append_tool_plan_contract_event,
    append_tool_plan_prompt_event,
    append_workflow_routing_policy_event,
)
from ._loop_request_tool_surface import RequestSurface, _ensure_named_tool_definitions, tool_names_of

if TYPE_CHECKING:
    from ._loop_request_messages import RuntimeMessagesInputs


def _trace(context_snapshot: dict[str, Any], key: str, value: Any, runtime_settings: dict[str, Any]) -> None:
    context_snapshot[key] = compact_trace_value(value, trace_limits=runtime_settings)


def _resolve_tool_plan(
    inputs: RuntimeMessagesInputs,
    surface: RequestSurface,
    context_snapshot: dict[str, Any],
    effective_workflow_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    """Session catalog, trace-only plan and execution control; filters the surface by that control."""
    runtime_settings = inputs.runtime_settings
    session_tool_catalog_resolution = resolve_session_tool_catalog(
        tool_definitions=surface.tool_definitions,
        capability_type=inputs.capability_type,
        request_analysis=inputs.request_analysis,
        workflow_contract=effective_workflow_contract,
        tool_context=inputs.tool_context,
    )
    session_tool_catalog = session_tool_catalog_resolution["catalog"]
    _trace(context_snapshot, "session_tool_catalog", session_tool_catalog, runtime_settings)
    _trace(context_snapshot, "session_tool_catalog_resolution", session_tool_catalog_resolution, runtime_settings)
    tool_plan_contract = build_trace_only_tool_plan_contract(
        current_turn_content=inputs.current_turn_content,
        request_analysis=inputs.request_analysis,
        workflow_contract=effective_workflow_contract,
        session_tool_catalog=session_tool_catalog,
        workflow_process_completed=bool(inputs.workflow_artifact_ready_for_final_response),
    )
    _trace(context_snapshot, "llm_tool_plan_contract", tool_plan_contract, runtime_settings)
    tool_execution_control_contract = build_tool_execution_control_contract(
        session_tool_catalog_resolution=session_tool_catalog_resolution,
        tool_plan_contract=tool_plan_contract,
    )
    if is_governed_coding_contract(effective_workflow_contract):
        # Governed coding runs are tool-governed by the approved step contract
        # plus the delivery gates; an LLM-drafted execution plan must not
        # filter or deny their toolset (a plan that picks the wrong delivery
        # tool and hides the rest deadlocks the run).
        tool_execution_control_contract = {}
    surface.tool_definitions, execution_control_runtime = filter_tool_definitions_for_execution_control(
        tool_definitions=surface.tool_definitions,
        execution_control_contract=tool_execution_control_contract,
    )
    surface.refresh_allowed()
    context_snapshot["tool_definition_count"] = len(surface.tool_definitions)
    context_snapshot["tool_names"] = sorted(surface.allowed_tool_names)
    _trace(context_snapshot, "tool_execution_control_runtime", execution_control_runtime, runtime_settings)
    _trace(context_snapshot, "tool_execution_control_contract", tool_execution_control_contract, runtime_settings)
    return {
        "session_tool_catalog": session_tool_catalog,
        "session_tool_catalog_resolution": session_tool_catalog_resolution,
        "tool_plan_contract": tool_plan_contract,
        "tool_execution_control_contract": tool_execution_control_contract,
    }


def _append_tool_plan_events(
    inputs: RuntimeMessagesInputs,
    surface: RequestSurface,
    context_snapshot: dict[str, Any],
    effective_workflow_contract: dict[str, Any] | None,
    plan: dict[str, Any],
) -> None:
    request_analysis = inputs.request_analysis
    append_context_prepared_event(
        context_snapshot,
        capability_type=inputs.capability_type,
        request_analysis=request_analysis,
        workflow_contract=effective_workflow_contract,
    )
    append_workflow_routing_policy_event(
        context_snapshot,
        routing_resolution=request_analysis.get("workflow_routing_policy_resolution"),
    )
    append_instructions_event(context_snapshot, instructions=request_analysis.get(INSTRUCTIONS_METADATA_KEY))
    append_tool_catalog_event(
        context_snapshot,
        allowed_tool_names=surface.allowed_tool_names,
        tool_definition_count=len(surface.tool_definitions),
        session_tool_catalog=plan["session_tool_catalog"],
        session_tool_catalog_resolution=plan["session_tool_catalog_resolution"],
    )
    append_tool_plan_contract_event(context_snapshot, tool_plan_contract=plan["tool_plan_contract"])
    append_tool_execution_control_event(
        context_snapshot,
        execution_control_contract=plan["tool_execution_control_contract"],
    )
    append_tool_plan_prompt_event(context_snapshot, prompt_packet=plan["tool_plan_prompt_packet"])


def apply_tool_plan(
    inputs: RuntimeMessagesInputs,
    surface: RequestSurface,
    context_snapshot: dict[str, Any],
    *,
    effective_workflow_contract: dict[str, Any] | None,
    deferred_catalog: Any,
) -> None:
    runtime_settings = inputs.runtime_settings
    plan = _resolve_tool_plan(inputs, surface, context_snapshot, effective_workflow_contract)
    plan["tool_plan_prompt_packet"] = build_tool_plan_prompt_packet(
        current_turn_content=inputs.current_turn_content,
        request_analysis=inputs.request_analysis,
        workflow_contract=effective_workflow_contract,
        session_tool_catalog=plan["session_tool_catalog"],
        draft_contract=plan["tool_plan_contract"],
    )
    _trace(context_snapshot, "llm_tool_plan_prompt_packet", plan["tool_plan_prompt_packet"], runtime_settings)
    if deferred_catalog:
        surface.request_messages = drop_unused_prompt_sections(
            surface.request_messages,
            (definition.get("function", {}).get("name") for definition in surface.tool_definitions),
        )
    _append_tool_plan_events(inputs, surface, context_snapshot, effective_workflow_contract, plan)


def apply_working_set(
    inputs: RuntimeMessagesInputs,
    surface: RequestSurface,
    context_snapshot: dict[str, Any],
) -> None:
    runtime_settings = inputs.runtime_settings
    surface.request_messages, working_set_stats = inputs.build_within_turn_working_set_messages(
        surface.request_messages,
        token_budget=int(inputs.context_plan.token_budget or 0),
        thinking_level=inputs.thinking_level,
        approx_chars_per_token=int(runtime_settings.get("approx_chars_per_token") or 4),
    )
    working_summary_message = inputs.build_turn_working_summary_message(
        surface.request_messages,
        thinking_level=inputs.thinking_level,
    )
    if working_summary_message is not None:
        surface.request_messages = [*surface.request_messages, working_summary_message]
    _trace(context_snapshot, "within_turn_working_set", working_set_stats, runtime_settings)
    if working_summary_message is not None:
        _trace(
            context_snapshot, "within_turn_working_summary", working_summary_message.get("content"), runtime_settings
        )


def plan_request_forced_tool_calls(
    inputs: RuntimeMessagesInputs,
    surface: RequestSurface,
    context_snapshot: dict[str, Any],
    *,
    planning_tool_history: list[dict[str, Any]],
    text_only_agent: bool,
) -> list[dict[str, Any]] | None:
    tool_context = inputs.tool_context
    forced_tool_calls = inputs.forced_tool_calls
    if not forced_tool_calls:
        forced_tool_calls = inputs.plan_forced_tool_calls_for_turn(
            request_analysis=inputs.request_analysis,
            capability_type=inputs.capability_type,
            current_turn_content=inputs.current_turn_content,
            workspace_root=str(tool_context.workspace_root),
            current_allowed_tool_names=surface.allowed_tool_names,
            turn_tool_history=planning_tool_history,
            covered_evidence_axes=inputs.covered_evidence_axes,
            workflow_contract_from_request_analysis=inputs.workflow_contract_from_request_analysis,
            plan_next_workflow_tool_calls=inputs.plan_next_workflow_tool_calls,
            _plan_coding_preflight_tool_calls=inputs._plan_coding_preflight_tool_calls,
            allow_coding_preflight=inputs.current_step is None,
        )
    forced_tool_names = {
        str((call.get("function") or {}).get("name") or call.get("tool_name") or "").strip()
        for call in (forced_tool_calls or [])
        if isinstance(call, dict)
        and str((call.get("function") or {}).get("name") or call.get("tool_name") or "").strip()
    }
    if forced_tool_names:
        surface.tool_definitions = _ensure_named_tool_definitions(
            surface.tool_definitions,
            forced_tool_names,
            agent_type=inputs.capability_type,
        )
        surface.allowed_tool_names = tool_names_of(surface.tool_definitions)
        context_snapshot["tool_definition_count"] = len(surface.tool_definitions)
        context_snapshot["tool_names"] = sorted(surface.allowed_tool_names)
    if text_only_agent and (forced_tool_calls or surface.tool_definitions):
        # Platform-planned calls are tool calls too; a text-only agent runs none of them.
        forced_tool_calls, surface.tool_definitions, surface.allowed_tool_names = None, [], set()
        context_snapshot["tool_definition_count"] = 0
        context_snapshot["tool_names"] = []
    append_forced_tool_plan_event(context_snapshot, forced_tool_calls=forced_tool_calls)
    return forced_tool_calls
