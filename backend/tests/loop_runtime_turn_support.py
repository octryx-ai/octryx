"""Dependency bundle for driving the real ``execute_runtime_turn``.

``execute_runtime_turn`` takes every collaborator as a field of its ``RuntimeTurnInputs``.
This module supplies inert stand-ins for all of them, so a test overrides
only the few it is actually about — the dispatched response, the usage
recorder, the database — and still runs the real turn body.
"""

from __future__ import annotations

import uuid
from typing import Any


class _ToolContext:
    request_id = "req-test"


async def _record_usage_event(**kwargs):
    return None


def _apply_workflow_response_override(**kwargs):
    return (
        kwargs["response"],
        kwargs["content"],
        kwargs["tool_calls"],
        kwargs["context_snapshot"],
        None,
    )


async def _handle_response_guards(inputs):
    return {}


async def _persist_runtime_assistant_response(**kwargs):
    return {"id": str(uuid.uuid4())}, {"id": "trace"}


async def _persist_traced_assistant_message(**kwargs):
    return None


async def _persist_suppressed_runtime_response(**kwargs):
    return None


async def _persist_turn_trace(**kwargs):
    return None


async def _build_runtime_error_salvage_message(**kwargs):
    return None


def _event_factory(**kwargs):
    return kwargs


async def _chat_with_runtime_fallback(**kwargs):
    raise AssertionError("chat_with_runtime_fallback should not be called in this unit test")


def _normalize_runtime_chat_result(result):
    return result


def _runtime_turn_state() -> dict[str, Any]:
    """Session, request and step-loop state of a fresh turn."""
    return {
        "db": None,
        "session_id": "session-1",
        "user_id": "user-1",
        "current_runtimes": [{"provider_name": "openrouter", "model": "fallback-model", "target_id": "fallback"}],
        "request_messages": [{"role": "user", "content": "hello"}],
        "current_tool_definitions": [],
        "provider_max_tokens": 512,
        "provider_reasoning_effort": None,
        "request_timeout_seconds": 30,
        "forced_tool_calls": None,
        "runtime_settings": {},
        "tool_context": _ToolContext(),
        "request_analysis": {},
        "covered_evidence_axes": set(),
        "current_allowed_tool_names": set(),
        "current_step": None,
        "current_step_index": 0,
        "current_step_iterations": 0,
        "current_step_max_iterations": 1,
        "current_step_tool_activity": False,
        "current_step_wrapup_forced": False,
        "active_steps": [],
        "current_turn_content": "",
        "capability_type": "chat",
        "context_plan": None,
        "turn_tool_history": [],
        "step_tool_history": [],
        "executed_tool_names": set(),
        "tdd_cycle_state": None,
        "total_tokens_in": 0,
        "total_tokens_out": 0,
        "consecutive_non_progress_response_count": 0,
        "consecutive_transitional_response_count": 0,
        "consecutive_coding_no_execution_count": 0,
        "context_snapshot": {},
        "messages": [],
    }


def _runtime_turn_collaborators() -> dict[str, Any]:
    """Inert collaborators: no dispatch, no-op persistence and permissive or negative predicates."""
    return {
        "chat_with_runtime_fallback": _chat_with_runtime_fallback,
        "normalize_runtime_chat_result": _normalize_runtime_chat_result,
        "dispatch_loop_runtime_response": None,
        "record_usage_event": _record_usage_event,
        "apply_workflow_response_override": _apply_workflow_response_override,
        "workflow_contract_from_request_analysis": lambda analysis: None,
        "plan_next_workflow_tool_calls": lambda **kwargs: [],
        "handle_response_guards": _handle_response_guards,
        "persist_traced_assistant_message": _persist_traced_assistant_message,
        "persist_runtime_assistant_response": _persist_runtime_assistant_response,
        "event_factory": _event_factory,
        "is_transitional_assistant_response": lambda *args, **kwargs: False,
        "is_transitional_tool_call_preamble": lambda *args, **kwargs: False,
        "is_non_substantive_assistant_response": lambda *args, **kwargs: False,
        "looks_like_step_completion_summary": lambda *args, **kwargs: False,
        "allows_noop_step_completion": lambda *args, **kwargs: False,
        "build_required_tool_reminder": lambda *args, **kwargs: "",
        "build_stalled_step_message": lambda *args, **kwargs: "",
        "persist_suppressed_runtime_response": _persist_suppressed_runtime_response,
        "persist_turn_trace": _persist_turn_trace,
        "build_tdd_cycle_incomplete_reminder": lambda *args, **kwargs: "",
        "build_initial_tdd_cycle_state": lambda: {},
        "is_tdd_cycle_complete": lambda *args, **kwargs: True,
        "is_tdd_cycle_step": lambda *args, **kwargs: False,
        "_has_meaningful_coding_execution": lambda *args, **kwargs: False,
        "_is_probable_coding_change_request": lambda *args, **kwargs: False,
        "_looks_like_coding_intent_only_response": lambda *args, **kwargs: False,
        "_is_self_review_step": lambda *args, **kwargs: False,
        "_is_self_review_step_complete": lambda *args, **kwargs: False,
        "_build_incomplete_self_review_reminder": lambda *args, **kwargs: "",
        "workflow_artifact_contract_satisfied": lambda *args, **kwargs: True,
        "_build_runtime_error_salvage_message": _build_runtime_error_salvage_message,
    }


def build_runtime_turn_kwargs() -> dict[str, Any]:
    return {**_runtime_turn_state(), **_runtime_turn_collaborators()}
