from app.agent.core.turn.decision_timeline import (
    append_context_prepared_event,
    append_forced_tool_plan_event,
    append_tool_catalog_event,
    append_tool_execution_control_event,
    append_tool_execution_event,
    append_tool_plan_contract_event,
    append_tool_plan_prompt_event,
    append_workflow_routing_policy_event,
)

DIAGRAM_WORKFLOW_CONTRACT = {
    "workflow_id": "generic_diagram",
    "workflow_class": "aws_topology_diagram_request",
    "workflow_contract_source": "db_routing_policy",
    "route_reason": "managed_profile",
    "diagram_source": "aws_topology_snapshot",
    "diagram_detail": "full",
}


AWS_DIAGRAM_SESSION_TOOL_CATALOG = {
    "mode": "trace_only",
    "contract_kind": "session_aware_tool_catalog",
    "contract_version": 2,
    "policy_source": "workflow_routing_policy",
    "routing_policy_id": "policy-1",
    "policy_allowlist_count": 3,
    "policy_denylist_count": 0,
}


AWS_DIAGRAM_CATALOG_RESOLUTION = {
    "contract_kind": "session_tool_catalog_resolution",
    "status": "resolved",
    "runtime_effect": "observational_only",
    "decision_summary": {
        "scope_source": "tool_context",
        "policy_effect_counts": {"denied": 0, "skipped": 0, "unavailable": 0},
    },
}


AWS_DIAGRAM_TOOL_PLAN_CONTRACT = {
    "mode": "trace_only",
    "source": "contract_draft",
    "intent_class": "aws_topology_diagram",
    "confidence": 0.85,
    "selected_tools": [{"tool": "aws_topology_snapshot"}, {"tool": "create_diagram"}],
    "max_tool_calls": 5,
    "requires_clarification": False,
    "validation": {"valid": True, "errors": [], "warnings": []},
}


AWS_DIAGRAM_EXECUTION_CONTROL = {
    "mode": "trace_only",
    "contract_kind": "tool_execution_control",
    "status": "ready",
    "runtime_effect": "observational_only",
    "intent_class": "aws_topology_diagram",
    "selected_tools": ["aws_topology_snapshot", "create_diagram"],
    "budget": {
        "max_tool_calls": 5,
        "planned_tool_count": 2,
        "remaining_after_plan": 3,
        "budget_exceeded": False,
    },
    "stop_criteria": ["diagram_artifact_created"],
    "validation": {"valid": True, "errors": [], "warnings": []},
    "policy_effects": {"counts": {"denied": 0, "skipped": 0, "unavailable": 0}},
    "blockers": [],
}


def test_decision_timeline_records_context_catalog_and_plan():
    snapshot = {}
    contract = DIAGRAM_WORKFLOW_CONTRACT

    append_context_prepared_event(
        snapshot,
        capability_type="admin",
        request_analysis={"requested_domains": ["aws"]},
        workflow_contract=contract,
    )
    append_tool_catalog_event(
        snapshot,
        allowed_tool_names={"aws_topology_snapshot", "create_diagram", "get_shape_library"},
        tool_definition_count=3,
        session_tool_catalog=AWS_DIAGRAM_SESSION_TOOL_CATALOG,
        session_tool_catalog_resolution=AWS_DIAGRAM_CATALOG_RESOLUTION,
    )
    append_tool_plan_contract_event(
        snapshot,
        tool_plan_contract=AWS_DIAGRAM_TOOL_PLAN_CONTRACT,
    )
    append_tool_execution_control_event(
        snapshot,
        execution_control_contract=AWS_DIAGRAM_EXECUTION_CONTROL,
    )
    append_forced_tool_plan_event(
        snapshot,
        forced_tool_calls=[
            {"function": {"name": "aws_topology_snapshot"}},
            {"function": {"name": "get_shape_library"}},
        ],
    )

    timeline = snapshot["decision_timeline"]
    assert [event["phase"] for event in timeline] == [
        "context",
        "catalog",
        "plan_contract",
        "execution_control",
        "plan",
    ]
    assert timeline[0]["metadata"]["workflow_id"] == "generic_diagram"
    assert timeline[0]["metadata"]["workflow_contract_source"] == "db_routing_policy"
    assert timeline[0]["metadata"]["workflow_class"] == "aws_topology_diagram_request"
    assert timeline[0]["metadata"]["diagram_source"] == "aws_topology_snapshot"
    assert timeline[1]["metadata"]["tool_count"] == 3
    assert timeline[1]["metadata"]["catalog_contract_kind"] == "session_aware_tool_catalog"
    assert timeline[1]["metadata"]["resolver_contract_kind"] == "session_tool_catalog_resolution"
    assert timeline[1]["metadata"]["resolver_status"] == "resolved"
    assert timeline[1]["metadata"]["resolver_scope_source"] == "tool_context"
    assert timeline[1]["metadata"]["policy_source"] == "workflow_routing_policy"
    assert timeline[1]["metadata"]["routing_policy_id"] == "policy-1"
    assert timeline[3]["metadata"]["contract_status"] == "ready"
    assert timeline[3]["metadata"]["max_tool_calls"] == 5
    assert timeline[4]["metadata"]["planned_tools"] == ["aws_topology_snapshot", "get_shape_library"]


def test_decision_timeline_marks_model_catalog_plan_when_no_forced_tools():
    snapshot = {}

    event = append_forced_tool_plan_event(snapshot, forced_tool_calls=None)

    assert event["phase"] == "plan"
    assert event["status"] == "info"
    assert event["title"] == "Model may choose from catalog"


def test_decision_timeline_records_tool_plan_contract():
    snapshot = {}

    event = append_tool_plan_contract_event(
        snapshot,
        tool_plan_contract={
            "mode": "trace_only",
            "source": "contract_draft",
            "intent_class": "aws_topology_diagram",
            "confidence": 0.85,
            "selected_tools": [{"tool": "aws_topology_snapshot"}, {"tool": "create_diagram"}],
            "max_tool_calls": 5,
            "requires_clarification": False,
            "validation": {"valid": True, "errors": [], "warnings": ["selected_tool_high_risk:create_diagram"]},
        },
    )

    assert event["phase"] == "plan_contract"
    assert event["status"] == "ok"
    assert event["metadata"]["intent_class"] == "aws_topology_diagram"
    assert event["metadata"]["selected_tools"] == ["aws_topology_snapshot", "create_diagram"]
    assert event["metadata"]["validation_warnings"] == ["selected_tool_high_risk:create_diagram"]


def test_decision_timeline_records_tool_plan_prompt_packet():
    snapshot = {}

    event = append_tool_plan_prompt_event(
        snapshot,
        prompt_packet={
            "mode": "trace_only",
            "source": "planner_prompt_packet",
            "planner_call_status": "not_called",
            "intent_hint": "knowledge_question",
            "allowed_tool_catalog": [{"name": "knowledge_search"}],
            "omitted_tool_count": 0,
        },
    )

    assert event["phase"] == "planner_io"
    assert event["title"] == "LLM planner prompt prepared"
    assert event["metadata"]["planner_call_status"] == "not_called"
    assert event["metadata"]["catalog_entry_count"] == 1


def test_decision_timeline_records_workflow_run_phase_resolution():
    snapshot = {}

    event = append_workflow_routing_policy_event(
        snapshot,
        routing_resolution={
            "source": "db",
            "status": "matched",
            "workflow_id": "knowledge_request",
            "workflow_class": "knowledge_request",
            "matched_group_id": None,
            "tool_policy": {"allowlist": ["knowledge_search", "knowledge_read"]},
            "safety_constraints": {"diagnosis_mode": True, "allow_mutating_tools": False},
        },
    )

    assert event["phase"] == "routing_policy"
    assert event["status"] == "ok"
    assert event["title"] == "Workflow run phase selected"
    assert event["metadata"]["workflow_id"] == "knowledge_request"
    assert event["metadata"]["workflow_class"] == "knowledge_request"
    assert event["metadata"]["allowed_tools"] == ["knowledge_read", "knowledge_search"]


def test_decision_timeline_records_tool_execution_errors():
    snapshot = {}

    event = append_tool_execution_event(
        snapshot,
        tool_results=[
            {"tool_name": "aws_topology_snapshot", "result": {"ok": True}},
            {"tool_name": "create_diagram", "result": {"error": "missing xml"}},
        ],
    )

    assert event["status"] == "error"
    assert event["metadata"]["executed_tools"] == ["aws_topology_snapshot", "create_diagram"]
    assert event["metadata"]["failed_tools"] == ["create_diagram"]


def test_decision_timeline_summarizes_tool_evidence_contracts():
    snapshot = {}

    event = append_tool_execution_event(
        snapshot,
        tool_results=[
            {
                "tool_name": "aws_topology_snapshot",
                "compact_result": {
                    "evidence_contract": {
                        "tool_name": "aws_topology_snapshot",
                        "status": "passed",
                        "hard_capped": False,
                        "missing_paths": [],
                    }
                },
            },
            {
                "tool_name": "get_confluence_page",
                "compact_result": {
                    "evidence_contract": {
                        "tool_name": "get_confluence_page",
                        "status": "failed",
                        "hard_capped": True,
                        "missing_paths": ["excerpt", "url"],
                    }
                },
            },
        ],
    )

    assert event["status"] == "warning"
    summary = event["metadata"]["evidence_contracts"]
    assert summary["contract_count"] == 2
    assert summary["passed_tools"] == ["aws_topology_snapshot"]
    assert summary["failed_tools"] == ["get_confluence_page"]
    assert summary["hard_capped_tools"] == ["get_confluence_page"]
    assert summary["missing_paths_by_tool"] == {"get_confluence_page": ["excerpt", "url"]}
