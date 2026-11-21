"""Runtime request preparation for a single standard loop iteration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services.workflow_contracts.registry import workflow_contract_from_request_analysis

from ..runtime._loop_runtime_turn_inputs import input_values
from ._loop_request_messages import RuntimeMessagesInputs, prepare_runtime_messages
from ._loop_request_routing import prepare_runtime_routing

if TYPE_CHECKING:
    from ..runtime._loop_runtime_cycle_inputs import RuntimeCycleInputs

# Cycle inputs the routing step receives unchanged.
_ROUTING_FIELDS = (
    "runtimes", "capability_type", "context_plan", "request_analysis", "current_step", "current_step_for_runtime",
    "step_tool_history", "_model_role_for_current_subtask",
)

# Cycle inputs the messages step receives unchanged; the routing result supplies the workflow contract, the
# runtimes and the reasoning settings.
_MESSAGES_FIELDS = (
    "runtime_target_id", "tool_definitions", "messages", "summary_context_msgs", "history", "thinking_level",
    "system_prompt", "personality_prompt", "memory_prompt", "skills_prompt", "system_context", "agent_definition",
    "context_plan", "request_analysis", "tool_context", "runtime_settings", "capability_type", "current_turn_content",
    "active_steps", "current_step", "current_step_for_runtime", "current_step_index", "elastic_iteration",
    "tdd_cycle_state", "existing_thread_context", "turn_diff_tracker", "turn_tool_history", "covered_evidence_axes",
    "workflow_artifact_ready_for_final_response", "workflow_final_answer_prompted", "forced_tool_calls",
    "build_current_step_prompt", "filter_tool_definitions", "build_turn_working_summary_message",
    "build_within_turn_working_set_messages", "plan_forced_tool_calls_for_turn", "_plan_coding_preflight_tool_calls",
    "_augment_step_allowed_tools_for_request_analysis",
    "_build_workflow_artifact_ready_message",
    "_latest_successful_tool_result_from_history",
    "plan_next_workflow_tool_calls",
)


def prepare_runtime_request(inputs: RuntimeCycleInputs) -> dict[str, Any]:
    routing = prepare_runtime_routing(**input_values(inputs, _ROUTING_FIELDS))
    messages_result = prepare_runtime_messages(RuntimeMessagesInputs(
        **input_values(inputs, _MESSAGES_FIELDS),
        workflow_contract=routing["workflow_contract"],
        current_runtimes=routing["current_runtimes"],
        current_coding_discipline=routing["current_coding_discipline"],
        current_reasoning_stage=routing["current_reasoning_stage"],
        current_reasoning_task_type=routing["current_reasoning_task_type"],
        current_subtask_role=routing["current_subtask_role"],
        workflow_contract_from_request_analysis=workflow_contract_from_request_analysis,
    ))

    return {
        "context_snapshot": messages_result["context_snapshot"],
        "current_allowed_tool_names": messages_result["current_allowed_tool_names"],
        "current_runtimes": routing["current_runtimes"],
        "current_tool_definitions": messages_result["current_tool_definitions"],
        "forced_tool_calls": messages_result["forced_tool_calls"],
        "request_messages": messages_result["request_messages"],
        "workflow_contract": routing["workflow_contract"],
        "workflow_final_answer_prompted": messages_result["workflow_final_answer_prompted"],
    }
