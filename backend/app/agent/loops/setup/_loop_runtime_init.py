"""Runtime state initialization for the standard agent loop."""

from __future__ import annotations


def initialize_loop_runtime_state(
    *,
    loop_state: dict[str, object],
    capability_type: str,
    thinking_level: str | None,
    agent_definition,
    runtime_settings: dict[str, object],
    max_completion_tokens_for_run,
) -> dict[str, object]:
    return {
        "request_timeout_seconds": float(runtime_settings.get("runtime_request_timeout_seconds") or 90),
        "duplicate_no_tool_response_count": 0,
        "repeated_previous_step_summary_count": 0,
        "consecutive_transitional_response_count": 0,
        "consecutive_coding_no_execution_count": 0,
        "consecutive_non_progress_response_count": 0,
        "provider_max_tokens": max_completion_tokens_for_run(
            capability_type,
            thinking_level,
            agent_definition,
            default_tokens=int(runtime_settings.get("default_completion_tokens") or 4096),
            extended_tokens=int(runtime_settings.get("extended_completion_tokens") or 8192),
        ),
        "total_tokens_in": loop_state["total_tokens_in"],
        "total_tokens_out": loop_state["total_tokens_out"],
        "forced_tool_calls": loop_state["forced_tool_calls"],
        "latest_repo_state": loop_state["latest_repo_state"],
        "last_no_tool_response_content": loop_state["last_no_tool_response_content"],
        "last_no_tool_response_signature": loop_state["last_no_tool_response_signature"],
        "last_no_tool_response_step_index": loop_state["last_no_tool_response_step_index"],
        "workflow_artifact_ready_for_final_response": loop_state["workflow_artifact_ready_for_final_response"],
        "workflow_contract": loop_state["workflow_contract"],
        "workflow_final_answer_prompted": loop_state["workflow_final_answer_prompted"],
    }
