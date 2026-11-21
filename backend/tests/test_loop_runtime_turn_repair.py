"""Runtime turn repair of textual tool requests under the tool policy."""

from __future__ import annotations

import json

from app.agent.loops.runtime._loop_textual_tool_repair import repair_textual_tool_request


def test_repair_textual_tool_request_uses_policy_authorized_tool_only() -> None:
    allowed_names: set[str] = set()
    context_snapshot = {
        "context_plan": {"tool_allowlist": ["knowledge_search"]},
        "session_tool_catalog": {
            "policy_allowlist": ["knowledge_read", "knowledge_changes"],
            "entries": [],
        },
        "request_analysis": {
            "workflow_contract": {
                "workflow_id": "knowledge_request",
                "allowed_tools": ["knowledge_read"],
            }
        },
    }

    repaired = repair_textual_tool_request(
        content='Tool request knowledge_read: {"query": "acme-orders"}',
        tool_calls=[],
        context_snapshot=context_snapshot,
        current_allowed_tool_names=allowed_names,
        capability_type="diagnosis",
    )

    assert repaired is not None
    assert repaired[0]["function"]["name"] == "knowledge_read"
    assert json.loads(repaired[0]["function"]["arguments"]) == {"query": "acme-orders"}
    assert "knowledge_read" in allowed_names
    assert context_snapshot["textual_tool_request_repair"]["status"] == "repaired"


def test_repair_textual_tool_request_rejects_tool_outside_policy() -> None:
    context_snapshot = {
        "session_tool_catalog": {"policy_allowlist": ["knowledge_search"]},
        "request_analysis": {"workflow_contract": {"allowed_tools": ["knowledge_search"]}},
    }

    repaired = repair_textual_tool_request(
        content="Tool request aws_read_operation: {'service': 'rds'}",
        tool_calls=[],
        context_snapshot=context_snapshot,
        current_allowed_tool_names=set(),
        capability_type="diagnosis",
    )

    assert repaired is None
