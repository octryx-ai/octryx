"""Tests for the connector-owned tool result compaction registry."""

from app.agent.engine import _compact_tool_result_for_model
from app.agent.engine.messages._tool_compaction_registry import (
    register_tool_result_compactor,
    resolve_tool_result_compactor,
)


def test_resolve_exact_name_beats_prefix_match():
    def _prefix_handler(result):
        return {"handled_by": "prefix"}

    def _exact_handler(result):
        return {"handled_by": "exact"}

    register_tool_result_compactor("registry_test_", _prefix_handler)
    register_tool_result_compactor("registry_test_exact", _exact_handler)

    assert resolve_tool_result_compactor("registry_test_exact")({}) == {"handled_by": "exact"}
    assert resolve_tool_result_compactor("registry_test_other")({}) == {"handled_by": "prefix"}


def test_resolve_prefers_longest_prefix():
    def _short_handler(result):
        return {"handled_by": "short"}

    def _long_handler(result):
        return {"handled_by": "long"}

    register_tool_result_compactor("registry_long_", _short_handler)
    register_tool_result_compactor("registry_long_prefix_", _long_handler)

    assert resolve_tool_result_compactor("registry_long_prefix_tool")({}) == {"handled_by": "long"}
    assert resolve_tool_result_compactor("registry_long_tool")({}) == {"handled_by": "short"}


def test_resolve_unknown_tool_returns_none():
    assert resolve_tool_result_compactor("registry_unregistered_tool_name") is None
    assert resolve_tool_result_compactor("") is None


def test_connector_handler_used_for_jira_result():
    compact = _compact_tool_result_for_model(
        "get_jira_ticket",
        {
            "key": "OPS-7",
            "summary": "Fix login flow",
            "status": {"name": "In Progress"},
            "assignee": {"displayName": "Jane Doe"},
        },
    )
    assert compact["key"] == "OPS-7"
    assert compact["summary"] == "Fix login flow"
    assert compact["status"] == "In Progress"
    assert compact["assignee"] == "Jane Doe"
    assert compact["answer_guidance"]["treat_jira_as_source_of_truth_for_task_scope"] is True


def test_neutral_fallback_for_unknown_tool():
    compact = _compact_tool_result_for_model(
        "some_totally_unknown_tool",
        {"nested": {"value": 42}, "items": [1, 2, 3]},
    )
    # Unknown tools fall through to the generic trace compaction, untouched by
    # any connector-owned handler.
    assert compact["nested"] == {"value": 42}
    assert compact["items"] == [1, 2, 3]


def test_error_results_bypass_connector_handlers():
    compact = _compact_tool_result_for_model("get_jira_ticket", {"error": "not found"})
    assert compact == {"error": "not found"}
