import json

from app.services.tool_catalog import build_session_tool_catalog
from app.services.tool_planning import (
    build_tool_plan_prompt_packet,
    build_trace_only_tool_plan_contract,
    parse_model_tool_plan_contract,
)
from app.tools.definitions import get_all_definitions


def _definition(name: str) -> dict:
    return get_all_definitions()[name]


def _catalog(*names: str, workflow_contract: dict | None = None) -> dict:
    return build_session_tool_catalog(
        tool_definitions=[_definition(name) for name in names],
        capability_type="admin",
        request_analysis={"requested_domains": ["aws"]},
        workflow_contract=workflow_contract,
    )


def test_tool_plan_prompt_packet_exposes_allowed_catalog_and_schema():
    workflow_contract = {"workflow_id": "knowledge_request"}
    catalog = _catalog("knowledge_search", "knowledge_read", workflow_contract=workflow_contract)
    request_analysis = {"requested_domains": ["knowledge"], "route_reason": "managed_profile"}
    draft = build_trace_only_tool_plan_contract(
        current_turn_content="What documentation do we have about onboarding?",
        request_analysis=request_analysis,
        workflow_contract=workflow_contract,
        session_tool_catalog=catalog,
    )

    packet = build_tool_plan_prompt_packet(
        current_turn_content="What documentation do we have about onboarding?",
        request_analysis=request_analysis,
        workflow_contract=workflow_contract,
        session_tool_catalog=catalog,
        draft_contract=draft,
    )

    assert packet["mode"] == "trace_only"
    assert packet["planner_call_status"] == "not_called"
    assert packet["intent_hint"] == "workflow_process"
    assert packet["intent_contract"]["intent_class"] == "workflow_process"
    assert packet["request_context"]["workflow_id"] == "knowledge_request"
    assert packet["request_context"]["denied_tools"] == []
    assert [entry["name"] for entry in packet["allowed_tool_catalog"]] == [
        "knowledge_read",
        "knowledge_search",
    ]
    assert "selected_tools" in packet["required_output_schema"]
    assert "Use only tools listed in allowed_tool_catalog." in packet["validation_rules"]


def test_parse_model_tool_plan_contract_validates_model_json():
    catalog = _catalog("knowledge_search", "knowledge_read")
    raw_content = json.dumps(
        {
            "version": 1,
            "mode": "trace_only",
            "intent_class": "workflow_process",
            "confidence": 0.82,
            "selected_tools": [
                {
                    "tool": "knowledge_search",
                    "reason": "Find source evidence.",
                    "expected_evidence": ["source_evidence"],
                }
            ],
            "stop_criteria": ["retrieved_source_evidence"],
            "max_tool_calls": 2,
            "requires_clarification": False,
        }
    )

    plan = parse_model_tool_plan_contract(raw_content, session_tool_catalog=catalog)

    assert plan["source"] == "model_response"
    assert plan["intent_class"] == "workflow_process"
    assert plan["selected_tools"][0]["tool"] == "knowledge_search"
    assert plan["validation"]["valid"] is True


def test_parse_model_tool_plan_contract_rejects_unknown_tools():
    catalog = _catalog("knowledge_search")

    plan = parse_model_tool_plan_contract(
        '{"version":1,"mode":"trace_only","intent_class":"workflow_process","confidence":0.7,'
        '"selected_tools":["bash"],"stop_criteria":["done"],"max_tool_calls":1}',
        session_tool_catalog=catalog,
    )

    assert plan["source"] == "model_response"
    assert plan["selected_tools"] == [{"tool": "bash", "reason": "", "expected_evidence": []}]
    assert plan["validation"]["valid"] is False
    assert plan["validation"]["errors"] == ["selected_tool_not_in_catalog:bash"]


def test_parse_model_tool_plan_contract_marks_non_json_response_invalid():
    plan = parse_model_tool_plan_contract("I would use the knowledge tools.", session_tool_catalog=_catalog())

    assert plan["source"] == "model_response_parse_error"
    assert plan["requires_clarification"] is True
    assert plan["validation"]["valid"] is False
    assert plan["validation"]["errors"] == ["planner_response_not_json"]
