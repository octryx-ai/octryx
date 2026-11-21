"""Enforcing the tool execution control contract allows planned tools, denies unplanned tools and exhausted budgets, and filters the visible tool definitions when ready."""

from app.services.tool_planning import enforce_tool_execution_control, filter_tool_definitions_for_execution_control
from tests.tool_execution_control_contract_support import _definition


def test_enforce_tool_execution_control_allows_planned_autonomous_source_tool():
    result = enforce_tool_execution_control(
        tool_name="knowledge_search",
        context_snapshot={
            "tool_execution_control_contract": {
                "contract_kind": "tool_execution_control",
                "intent_class": "source_evidence_lookup",
                "selected_tools": ["knowledge_search", "search_jira_tickets"],
                "budget": {"max_tool_calls": 4},
                "enforcement": {"enabled": True, "max_tool_calls": 4},
            }
        },
        turn_tool_history=[],
    )

    assert result is None


def test_enforce_tool_execution_control_denies_unplanned_tool():
    result = enforce_tool_execution_control(
        tool_name="aws_topology_snapshot",
        context_snapshot={
            "tool_execution_control_contract": {
                "contract_kind": "tool_execution_control",
                "intent_class": "knowledge_question",
                "selected_tools": ["knowledge_search", "knowledge_read"],
                "budget": {"max_tool_calls": 4},
                "enforcement": {"enabled": True, "max_tool_calls": 4},
            }
        },
        turn_tool_history=[],
    )

    assert result is not None
    assert result["code"] == "tool_execution_control_denied"
    assert result["reason"] == "tool_not_in_execution_plan"
    assert result["allowed_tools"] == ["knowledge_read", "knowledge_search"]


def test_enforce_tool_execution_control_denies_exhausted_budget():
    result = enforce_tool_execution_control(
        tool_name="knowledge_read",
        context_snapshot={
            "tool_execution_control_contract": {
                "contract_kind": "tool_execution_control",
                "intent_class": "knowledge_question",
                "selected_tools": ["knowledge_search", "knowledge_read"],
                "budget": {"max_tool_calls": 1},
                "enforcement": {"enabled": True, "max_tool_calls": 1},
            }
        },
        turn_tool_history=[{"tool_name": "knowledge_search", "result": {"status": "ok"}}],
    )

    assert result is not None
    assert result["code"] == "tool_execution_control_budget_exhausted"
    assert result["used_tool_calls"] == 1
    assert result["max_tool_calls"] == 1


def test_enforce_tool_execution_control_is_inactive_for_non_ready_contract():
    assert (
        enforce_tool_execution_control(
            tool_name="todo_read",
            context_snapshot={
                "tool_execution_control_contract": {
                    "status": "clarification_required",
                    "selected_tools": [],
                    "enforcement": {"enabled": False},
                }
            },
            turn_tool_history=[],
        )
        is None
    )


def test_filter_tool_definitions_for_execution_control_limits_visible_tools_when_ready():
    definitions = [_definition("knowledge_search"), _definition("knowledge_read"), _definition("aws_topology_snapshot")]

    filtered, runtime = filter_tool_definitions_for_execution_control(
        tool_definitions=definitions,
        execution_control_contract={
            "selected_tools": ["knowledge_search", "knowledge_read"],
            "enforcement": {"enabled": True, "max_tool_calls": 4},
        },
    )

    assert [(item["function"]["name"]) for item in filtered] == ["knowledge_search", "knowledge_read"]
    assert runtime["applied"] is True
    assert runtime["visible_tool_count"] == 2
    assert runtime["selected_tool_count"] == 2


def test_filter_tool_definitions_for_execution_control_keeps_catalog_for_inactive_contract():
    definitions = [_definition("todo_read"), _definition("aws_topology_snapshot")]

    filtered, runtime = filter_tool_definitions_for_execution_control(
        tool_definitions=definitions,
        execution_control_contract={
            "selected_tools": [],
            "enforcement": {"enabled": False},
        },
    )

    assert filtered == definitions
    assert runtime["applied"] is False


def test_filter_tool_definitions_for_execution_control_keeps_autonomous_source_tools_when_ready():
    definitions = [_definition("knowledge_search"), _definition("search_jira_tickets")]

    filtered, runtime = filter_tool_definitions_for_execution_control(
        tool_definitions=definitions,
        execution_control_contract={
            "selected_tools": ["knowledge_search", "search_jira_tickets"],
            "enforcement": {"enabled": True, "max_tool_calls": 4},
        },
    )

    assert [item["function"]["name"] for item in filtered] == ["knowledge_search", "search_jira_tickets"]
    assert runtime["applied"] is True
    assert runtime["reason"] == "ready_execution_control_contract"
