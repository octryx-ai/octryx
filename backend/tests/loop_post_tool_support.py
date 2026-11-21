"""Shared handle_post_tool_outcome kwargs for the test_loop_post_tool_* modules."""

from app.services.loop_recovery import plan_loop_recovery


async def _noop_async(*args, **kwargs):  # type: ignore[no-untyped-def]
    return None


def _build_kwargs(  # type: ignore[no-untyped-def]
    *,
    wrapup_forced: bool,
    persist_traced_assistant_message,
    persist_synthesized_tool_assistant=_noop_async,
    stuck_loop_kind: str = "repetitive_tool_error_loop",
    tool_results: list[dict[str, object]] | None = None,
    workflow_contract: dict[str, object] | None = None,
    active_steps: list[dict[str, object]] | None = None,
    turn_tool_history: list[dict[str, object]] | None = None,
    current_user_message: str = "Research ticketing API integration and create a concise cited Word report.",
    current_step: dict[str, object] | None = None,
    request_analysis: dict[str, object] | None = None,
):
    effective_tool_results = tool_results or [{"tool_name": "web_search", "result": {"error": "DuckDuckGo search failed"}}]
    effective_active_steps = active_steps or [{"name": "Gather Sources"}]
    return {
        "db": None,
        "session_id": "session-1",
        "runtime": {"provider_name": "copilot"},
        "response": {"usage": {}},
        "request_messages": [],
        "context_snapshot": {"stuck_loop_detector": {"kind": stuck_loop_kind, "message": "web_search stalled"}},
        "tool_results": effective_tool_results,
        "current_user_message": current_user_message,
        "content": "I will try another search.",
        "total_tokens_in": 0,
        "total_tokens_out": 0,
        "usage_model": "gpt-test",
        "event_factory": lambda **kwargs: kwargs,
        "fetch_thread_context_state": _noop_async,
        "persist_synthesized_tool_assistant": persist_synthesized_tool_assistant,
        "persist_traced_assistant_message": persist_traced_assistant_message,
        "runtime_attempts": [],
        "request_analysis": request_analysis or {},
        "turn_tool_history": turn_tool_history or [],
        "workflow_contract": workflow_contract,
        "workflow_artifact_ready_for_final_response": False,
        "current_allowed_tool_names": {"web_search"},
        "covered_evidence_axes": set(),
        "current_step": current_step if current_step is not None else {"name": "Gather Sources"},
        "tdd_cycle_state": None,
        "current_step_index": 0,
        "active_steps": effective_active_steps,
        "current_step_wrapup_forced": wrapup_forced,
        "current_step_iterations": 1,
        "current_step_max_iterations": 2,
        "runtime_settings": {},
        "required_domains": set(),
        "covered_summary_domains": set(),
        "agent_definition": None,
        "executed_tool_names": {"web_search"},
        "context_plan": None,
        "has_pending_approval_result": lambda results: False,
        "_has_awaiting_subagent_result": lambda results: False,
        "_has_pending_clarification_result": lambda results: False,
        "_latest_successful_tool_result_from_results": lambda results, tool_name: None,
        "_is_jira_sprint_planner": lambda definition: False,
        "_build_jira_sprint_bundle_report": lambda result: None,
        "format_repository_noop_sync_report": lambda results: None,
        "format_repository_knowledge_sync_report": lambda results: None,
        "format_recent_bitbucket_commits_report": lambda result: "",
        "build_iteration_ceiling_event": lambda **kwargs: {},
        "plan_loop_recovery": plan_loop_recovery,
        "stuck_loop_event": {
            "kind": stuck_loop_kind,
            "message": "Step 'Gather Sources' is stagnating because `web_search` keeps failing.",
        },
        "is_tdd_cycle_step": lambda step: False,
        "is_tdd_cycle_complete": lambda state: False,
    }
