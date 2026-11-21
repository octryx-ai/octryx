"""A tool name no tool carries is reported as unknown, not as a capability the run lacks."""

from __future__ import annotations

from app.services.run_capability.declared import validate_declared_capability_class
from app.services.run_capability.definition_contract import validate_definition_capability_class


def test_a_flow_naming_an_unknown_tool_gets_an_unknown_tool_error():
    errors = validate_declared_capability_class("change", tool_names=["no_such_tool_xyz"], subject="Flow definition")
    assert errors == [{"code": "unknown_tool", "message": "Flow definition: unknown tool: no_such_tool_xyz."}]


def test_a_known_tool_is_still_checked_against_the_class():
    assert validate_declared_capability_class("read_only", tool_names=["knowledge_search"], subject="Flow") == []
    errors = validate_declared_capability_class("read_only", tool_names=["create_jira_ticket"], subject="Flow")
    assert [error["code"] for error in errors] == ["capability_class_exceeded"]


def test_a_workflow_contract_naming_an_unknown_tool_gets_an_unknown_tool_error():
    errors, _warnings = validate_definition_capability_class(
        is_definition=True,
        workflow_contract={"capability_class": "change", "allowed_tools": ["no_such_tool_xyz"]},
        tool_policy=None,
        safety_constraints=None,
    )
    assert {"code": "unknown_tool", "message": "unknown tool: no_such_tool_xyz."} in errors
    assert not any(error["code"] == "capability_class_exceeded" for error in errors)
