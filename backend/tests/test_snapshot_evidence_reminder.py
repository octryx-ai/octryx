"""Tests for the post-snapshot situational reminder (S4 of the catalog plan)."""

from __future__ import annotations

from app.agent.loops.response._loop_snapshot_reminder import append_snapshot_evidence_reminder


def _snapshot_result(tool_name: str = "aws_topology_snapshot") -> dict:
    return {"tool_name": tool_name, "result": {"diagram_brief": {"mode": "compact"}}}


def test_reminder_fires_after_successful_snapshot():
    messages: list[dict] = []

    appended = append_snapshot_evidence_reminder(
        messages=messages,
        tool_results=[_snapshot_result()],
        turn_tool_history=[_snapshot_result()],
        current_allowed_tool_names={"create_diagram", "aws_topology_snapshot"},
    )

    assert appended is True
    assert messages[-1]["role"] == "system"
    assert "aws_topology_snapshot succeeded" in messages[-1]["content"]
    assert "create_diagram" in messages[-1]["content"]


def test_reminder_skips_failed_snapshot_and_non_snapshot_tools():
    messages: list[dict] = []

    assert not append_snapshot_evidence_reminder(
        messages=messages,
        tool_results=[{"tool_name": "aws_topology_snapshot", "result": {"error": "denied"}}],
        turn_tool_history=[],
        current_allowed_tool_names={"create_diagram"},
    )
    assert not append_snapshot_evidence_reminder(
        messages=messages,
        tool_results=[{"tool_name": "knowledge_search", "result": {"count": 1}}],
        turn_tool_history=[],
        current_allowed_tool_names={"create_diagram"},
    )
    assert messages == []


def test_reminder_skips_when_diagram_already_created():
    messages: list[dict] = []

    appended = append_snapshot_evidence_reminder(
        messages=messages,
        tool_results=[_snapshot_result("code_structure_snapshot")],
        turn_tool_history=[
            _snapshot_result("code_structure_snapshot"),
            {"tool_name": "create_diagram", "result": {"status": "created", "diagram_id": "abc"}},
        ],
        current_allowed_tool_names={"create_diagram"},
    )

    assert appended is False
    assert messages == []


def test_reminder_skips_when_diagram_tool_not_allowed():
    messages: list[dict] = []

    appended = append_snapshot_evidence_reminder(
        messages=messages,
        tool_results=[_snapshot_result()],
        turn_tool_history=[],
        current_allowed_tool_names={"aws_topology_snapshot"},
    )

    assert appended is False
    assert messages == []
