"""Tool execution helpers for the standard agent loop."""

from __future__ import annotations

import json
from typing import Any

from ....models.json_text import safe_json_dict
from ....services.workflow_checks.evidence import evidence_history_fields
from ....tools.tool_names import ToolName
from ...core.guards.tdd_cycle import export_tdd_cycle_state, is_tdd_cycle_step, record_tdd_cycle_tool_result
from ...core.runtime.trace_runtime import compact_trace_value
from ._loop_tool_calls_inputs import ToolBatchState, TurnToolCallsInputs


def _history_result_for_prompt(
    tool_result: dict[str, Any],
    *,
    raw_result: dict[str, Any],
    runtime_settings: dict[str, Any],
) -> dict[str, Any]:
    """Keep prompt-facing tool history compact while raw payloads stay persisted."""

    compact_result = tool_result.get("compact_result")
    if isinstance(compact_result, dict):
        prompt_result = dict(compact_result)
        source = "compact_result"
    else:
        prompt_result = compact_trace_value(raw_result, trace_limits=runtime_settings)
        if not isinstance(prompt_result, dict):
            prompt_result = {"value": prompt_result}
        source = "compact_trace"

    artifact_id = str(tool_result.get("artifact_id") or "").strip()
    if artifact_id:
        prompt_result.setdefault("artifact_id", artifact_id)
    prompt_result.setdefault("_prompt_result_source", source)
    return prompt_result


def _enforce_deterministic_tool_calls(
    tool_calls: list[dict[str, Any]], inputs: TurnToolCallsInputs
) -> list[dict[str, Any]]:
    context_snapshot = inputs.context_snapshot
    # Binding evidence rule at the single dispatch choke point: no response
    # branch (native tool calls, textual repair, provider inline conversion)
    # can put freehand diagram XML past this line once the turn holds an AWS
    # topology snapshot.
    from ..request._loop_evidence_diagrams import enforce_evidence_backed_diagrams

    enforced_diagrams = enforce_evidence_backed_diagrams(
        tool_calls=tool_calls,
        turn_tool_history=inputs.turn_tool_history,
        allowed_tool_names=inputs.current_allowed_tool_names,
    )
    if enforced_diagrams is not None:
        tool_calls, diagram_audit = enforced_diagrams
        context_snapshot["evidence_diagram_enforcement"] = diagram_audit
    return tool_calls


def _prepared_tool_call(
    tool_call: dict[str, Any], inputs: TurnToolCallsInputs, state: ToolBatchState
) -> tuple[str, dict[str, Any]]:
    """The call's tool name and the call to dispatch (step branch prefix applied)."""
    func = tool_call.get("function", {})
    tool_name = func.get("name", "")
    tool_args_str = func.get("arguments", "{}")
    if isinstance(tool_args_str, str):
        tool_args_preview = safe_json_dict(tool_args_str)
    elif isinstance(tool_args_str, dict):
        tool_args_preview = tool_args_str
    else:
        tool_args_preview = {}
    current_step = inputs.current_step
    if (
        tool_name == ToolName.PREPARE_BITBUCKET_REPOSITORY
        and current_step
        and current_step.get("branchPrefix")
        and not tool_args_preview.get("branch_name")
        and not tool_args_preview.get("branch_prefix")
    ):
        tool_call = {
            **tool_call,
            "function": {
                **func,
                "arguments": json.dumps({**tool_args_preview, "branch_prefix": current_step["branchPrefix"]}),
            },
        }
    return tool_name, tool_call


async def _execute_tool_call(tool_call: dict[str, Any], inputs: TurnToolCallsInputs, state: ToolBatchState) -> Any:
    return await inputs.execute_tool_call_for_turn(
        db=inputs.db,
        assistant_message_id=inputs.assistant_msg.id,
        tool_call=tool_call,
        tool_context=inputs.tool_context,
        active_steps=inputs.active_steps,
        current_step_index=state.current_step_index,
        current_step_tool_activity=state.current_step_tool_activity,
        current_allowed_tool_names=state.current_allowed_tool_names,
        latest_repo_state=state.latest_repo_state,
        infer_repo_tool_args=inputs.infer_repo_tool_args,
        resolve_allowed_tools_for_step_tool_call=inputs.resolve_allowed_tools_for_step_tool_call,
        compact_tool_result_for_model=inputs.compact_tool_result_for_model,
        summary_domains_satisfied_by_result=inputs.summary_domains_satisfied_by_result,
        execute_tool=inputs.execute_tool,
        turn_diff_tracker=inputs.turn_diff_tracker,
        context_snapshot=inputs.context_snapshot,
        turn_tool_history=inputs.turn_tool_history,
    )


def _record_executed_tool(
    executed_tool: Any, tool_name: str, inputs: TurnToolCallsInputs, state: ToolBatchState
) -> None:
    """Append the executed call to the model messages and histories and update the turn's trace state."""
    runtime_settings = inputs.runtime_settings
    context_snapshot = inputs.context_snapshot
    result = executed_tool.tool_result.get("result") or {}
    prompt_result = _history_result_for_prompt(
        executed_tool.tool_result,
        raw_result=result if isinstance(result, dict) else {},
        runtime_settings=runtime_settings,
    )
    inputs.messages.append(executed_tool.message_for_model)
    state.step_tool_history.append(
        {
            "tool_name": tool_name,
            "params": dict(executed_tool.tool_args or {}),
            "result": prompt_result,
        }
    )
    inputs.turn_tool_history.append(
        {
            "tool_name": tool_name,
            "params": dict(executed_tool.tool_args or {}),
            "result": prompt_result,
            "persisted_call_id": executed_tool.tool_result.get("artifact_id"),
            # The workflow checks judge a test run by its full result, never the model's shortened copy.
            **evidence_history_fields(tool_name, result),
        }
    )
    context_snapshot["turn_diff"] = compact_trace_value(
        inputs.turn_diff_tracker.to_dict(), trace_limits=runtime_settings
    )
    inputs.executed_tool_names.add(tool_name)
    inputs.covered_summary_domains.update(executed_tool.covered_domains)
    current_step = inputs.current_step
    tdd_cycle_state = inputs.tdd_cycle_state
    if current_step and is_tdd_cycle_step(current_step) and tdd_cycle_state is not None:
        record_tdd_cycle_tool_result(tdd_cycle_state, tool_name, result if isinstance(result, dict) else {})
        context_snapshot["tdd_cycle"] = compact_trace_value(
            export_tdd_cycle_state(tdd_cycle_state), trace_limits=runtime_settings
        )


async def execute_turn_tool_calls(inputs: TurnToolCallsInputs) -> dict[str, Any]:
    tool_calls = _enforce_deterministic_tool_calls(inputs.tool_calls, inputs)
    state = ToolBatchState.from_inputs(inputs)
    tool_results = []
    for tool_call in tool_calls:
        tool_name, tool_call = _prepared_tool_call(tool_call, inputs, state)
        executed_tool = await _execute_tool_call(tool_call, inputs, state)
        state.apply(executed_tool)
        tool_results.append(executed_tool.tool_result)
        _record_executed_tool(executed_tool, tool_name, inputs, state)

    recent_tool_names = [
        str(item.get("tool_name") or "").strip()
        for item in state.step_tool_history[-3:]
        if str(item.get("tool_name") or "").strip()
    ]
    return {
        "context_snapshot": inputs.context_snapshot,
        "current_allowed_tool_names": state.current_allowed_tool_names,
        "current_step_index": state.current_step_index,
        "current_step_iterations": state.current_step_iterations,
        "current_step_tool_activity": state.current_step_tool_activity,
        "duplicate_no_tool_response_count": 0,
        "executed_tool_names": inputs.executed_tool_names,
        "last_no_tool_response_content": "",
        "last_no_tool_response_signature": None,
        "last_no_tool_response_step_index": None,
        "latest_repo_state": state.latest_repo_state,
        "recent_tool_names": recent_tool_names,
        "repeated_previous_step_summary_count": 0,
        "step_tool_history": state.step_tool_history,
        "step_tool_history_index": state.step_tool_history_index,
        "tool_results": tool_results,
        "turn_tool_history": inputs.turn_tool_history,
    }
