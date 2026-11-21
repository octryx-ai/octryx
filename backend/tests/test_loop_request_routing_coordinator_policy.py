from __future__ import annotations

from typing import Any

from app.agent.loops.request._loop_request_routing import prepare_runtime_routing


def _build_kwargs() -> dict[str, Any]:
    return {
        "runtimes": [{"target_id": "runtime-a", "provider_name": "openai"}],
        "capability_type": "chat",
        "context_plan": None,
        "request_analysis": {},
        "current_step": None,
        "current_step_for_runtime": None,
        "step_tool_history": [],
        "_model_role_for_current_subtask": lambda **kwargs: "analyst",
    }


def test_prepare_runtime_routing_exposes_deterministic_workflow_mode() -> None:
    kwargs = _build_kwargs()
    kwargs["request_analysis"] = {"workflow_contract": {"workflow_id": "multi_source_summary"}}

    routing = prepare_runtime_routing(**kwargs)

    assert routing["workflow_contract"] == {"workflow_id": "multi_source_summary"}
    assert routing["coordinator_routing"]["mode"] == "deterministic_workflow"
    assert routing["coordinator_routing"]["explicit"] is True
    assert routing["coordinator_routing"]["signals"]["deterministic_workflow_id"] == "multi_source_summary"


def test_prepare_runtime_routing_exposes_worker_delegation_mode_from_request_analysis() -> None:
    kwargs = _build_kwargs()
    kwargs["request_analysis"] = {
        "requires_worker_assignment": True,
        "required_worker_domain": "kubernetes",
        "requested_action": "diagnose",
    }

    routing = prepare_runtime_routing(**kwargs)

    assert routing["coordinator_routing"]["mode"] == "worker_delegation"
    assert routing["coordinator_routing"]["signals"]["required_worker_domain"] == "kubernetes"
    assert routing["coordinator_routing"]["signals"]["requested_action"] == "diagnose"


def test_prepare_runtime_routing_prefers_runtime_step_coordinator_signals() -> None:
    kwargs = _build_kwargs()
    kwargs["current_step"] = {"requires_parent_resume": False}
    kwargs["current_step_for_runtime"] = {
        "requires_parent_resume": True,
        "expected_child_count": 2,
    }

    routing = prepare_runtime_routing(**kwargs)

    assert routing["coordinator_routing"]["mode"] == "sub_agent_group"
    assert routing["coordinator_routing"]["signals"]["requires_parent_resume"] is True
    assert routing["coordinator_routing"]["signals"]["expected_child_count"] == 2


def test_prepare_runtime_routing_keeps_conflicts_explicit() -> None:
    kwargs = _build_kwargs()
    kwargs["request_analysis"] = {
        "workflow_contract": {"workflow_id": "multi_source_summary"},
        "required_worker_domain": "kubernetes",
    }

    routing = prepare_runtime_routing(**kwargs)

    assert routing["coordinator_routing"]["mode"] == "manual_review"
    assert routing["coordinator_routing"]["explicit"] is False
    assert routing["coordinator_routing"]["conflicts"] == [
        "deterministic workflow matched",
        "worker assignment matched",
    ]
