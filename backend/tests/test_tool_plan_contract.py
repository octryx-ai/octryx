"""The tool plan contract never infers intent from prompt keywords, selects knowledge workflow tools, rejects tools outside the catalog and asks for clarification on an unknown intent."""

from app.services.tool_planning import build_trace_only_tool_plan_contract, validate_tool_plan_contract
from tests.tool_plan_contract_support import _catalog


def test_tool_plan_contract_never_infers_intent_from_prompt_keywords():
    """Without a workflow contract, keyword-laden prompts stay 'unknown'.

    The deterministic draft never guesses an intent from prompt text; the
    turn requires clarification or a plain direct answer instead.
    """
    catalog = _catalog("knowledge_search", "knowledge_read", "knowledge_changes")

    plan = build_trace_only_tool_plan_contract(
        current_turn_content="What can you tell me about Report Builder from knowledge?",
        request_analysis={"requested_domains": ["knowledge"]},
        workflow_contract=None,
        session_tool_catalog=catalog,
    )

    assert plan["intent_class"] == "unknown"
    assert plan["selected_tools"] == []
    assert plan["requires_clarification"] is True
    assert plan["intent_contract"]["version"] == 1
    assert plan["intent_contract"]["source"] == "deterministic_trace_contract"
    assert plan["intent_contract"]["intent_class"] == "unknown"
    assert plan["intent_contract"]["requested_domains"] == ["knowledge"]
    assert plan["intent_contract"]["catalog_policy_source"] == "no_workflow_routing_policy"
    assert plan["intent_contract"]["fallback_policy"] == "clarify_or_answer_without_tools"
    assert plan["validation"]["valid"] is True


def test_tool_plan_contract_selects_workflow_phase_tools_for_knowledge_contract():
    """Knowledge tools are drafted only for an explicit knowledge workflow contract."""
    workflow_contract = {"workflow_id": "knowledge_request"}
    catalog = _catalog("knowledge_search", "knowledge_read", workflow_contract=workflow_contract)

    plan = build_trace_only_tool_plan_contract(
        current_turn_content="What documentation do we have about onboarding?",
        request_analysis={"requested_domains": ["knowledge"]},
        workflow_contract=workflow_contract,
        session_tool_catalog=catalog,
    )

    assert plan["intent_class"] == "workflow_process"
    # Both governed phase tools in the catalog are drafted.
    assert {item["tool"] for item in plan["selected_tools"]} == {"knowledge_search", "knowledge_read"}
    assert plan["validation"]["valid"] is True


def test_tool_plan_contract_validator_rejects_tools_outside_catalog():
    catalog = _catalog("knowledge_search")
    plan = {
        "version": 1,
        "mode": "trace_only",
        "intent_class": "workflow_process",
        "confidence": 0.8,
        "selected_tools": [{"tool": "bash", "reason": "bad", "expected_evidence": ["shell"]}],
        "stop_criteria": ["retrieved_source_evidence"],
        "max_tool_calls": 1,
    }

    validation = validate_tool_plan_contract(plan, session_tool_catalog=catalog)

    assert validation["valid"] is False
    assert validation["errors"] == ["selected_tool_not_in_catalog:bash"]


def test_tool_plan_contract_unknown_intent_requires_clarification_without_tools():
    plan = build_trace_only_tool_plan_contract(
        current_turn_content="Hello there",
        request_analysis={"requested_domains": []},
        workflow_contract=None,
        session_tool_catalog=_catalog(),
    )

    assert plan["intent_class"] == "unknown"
    assert plan["requires_clarification"] is True
    assert plan["selected_tools"] == []
    assert plan["validation"]["valid"] is True
