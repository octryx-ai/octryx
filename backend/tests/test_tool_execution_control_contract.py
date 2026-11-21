"""The tool execution control contract marks ready plans, required clarifications, and unavailable policy-required tools."""

from app.services.tool_catalog import resolve_session_tool_catalog
from app.services.tool_planning import build_tool_execution_control_contract, build_trace_only_tool_plan_contract
from tests.tool_execution_control_contract_support import _definition


def test_tool_execution_control_contract_marks_ready_plan():
    # S5: plans draft tools only from an explicit workflow contract.
    workflow_contract = {"workflow_id": "knowledge_request"}
    resolution = resolve_session_tool_catalog(
        tool_definitions=[
            _definition("knowledge_search"),
        ],
        capability_type="diagnosis",
        request_analysis={"requested_domains": ["knowledge"]},
        workflow_contract=workflow_contract,
    )
    plan = build_trace_only_tool_plan_contract(
        current_turn_content="What do we know about Report Builder?",
        request_analysis={"requested_domains": ["knowledge"]},
        workflow_contract=workflow_contract,
        session_tool_catalog=resolution["catalog"],
    )

    contract = build_tool_execution_control_contract(
        session_tool_catalog_resolution=resolution,
        tool_plan_contract=plan,
    )

    assert contract["contract_kind"] == "tool_execution_control"
    assert contract["status"] == "ready"
    assert contract["mode"] == "runtime_enforced"
    assert contract["runtime_effect"] == "selected_tool_and_budget_gate"
    assert contract["enforcement"] == {
        "enabled": True,
        "selected_tool_gate": True,
        "budget_gate": True,
        # One call per knowledge_request phase tool: the governed evidence search, read and changes,
        # and the memory recall beside them.
        "max_tool_calls": 4,
    }
    assert contract["selected_tools"] == ["knowledge_search"]
    assert contract["budget"]["max_tool_calls"] == 4
    assert contract["budget"]["planned_tool_count"] == 1
    assert contract["budget"]["remaining_after_plan"] == 3
    assert contract["blockers"] == []


def test_tool_execution_control_contract_marks_clarification_required():
    resolution = resolve_session_tool_catalog(
        tool_definitions=[],
        capability_type="diagnosis",
        request_analysis={"requested_domains": []},
        workflow_contract=None,
    )
    plan = build_trace_only_tool_plan_contract(
        current_turn_content="Hello there",
        request_analysis={"requested_domains": []},
        workflow_contract=None,
        session_tool_catalog=resolution["catalog"],
    )

    contract = build_tool_execution_control_contract(
        session_tool_catalog_resolution=resolution,
        tool_plan_contract=plan,
    )

    assert contract["status"] == "clarification_required"
    assert contract["runtime_effect"] == "inactive_until_ready"
    assert contract["enforcement"]["enabled"] is False
    assert contract["selected_tools"] == []
    assert contract["blockers"] == ["clarification_required"]


def test_tool_execution_control_contract_reports_policy_required_tools_unavailable():
    resolution = resolve_session_tool_catalog(
        tool_definitions=[],
        capability_type="diagnosis",
        request_analysis={
            "requested_domains": ["knowledge"],
            "workflow_routing_policy_resolution": {
                "source": "db",
                "status": "matched",
                "policy_id": "policy-knowledge",
                "policy_version_id": "version-knowledge",
                "matched_group_id": "knowledge-query",
                "tool_policy": {
                    "allowlist": ["knowledge_search"],
                    "denylist": [],
                },
            },
        },
        workflow_contract=None,
    )
    plan = {
        "version": 1,
        "mode": "trace_only",
        "intent_class": "workflow_process",
        "confidence": 0.45,
        "selected_tools": [],
        "stop_criteria": ["retrieved_source_evidence"],
        "max_tool_calls": 4,
        "requires_clarification": False,
        "validation": {"valid": True, "errors": [], "warnings": ["known_intent_has_no_available_tools"]},
    }

    contract = build_tool_execution_control_contract(
        session_tool_catalog_resolution=resolution,
        tool_plan_contract=plan,
    )

    assert contract["status"] == "blocked"
    assert contract["policy_effects"]["counts"]["unavailable"] == 1
    assert contract["policy_effects"]["unavailable_policy_tools"] == ["knowledge_search"]
    assert contract["blockers"] == ["policy_required_tools_unavailable", "no_selected_tools"]
