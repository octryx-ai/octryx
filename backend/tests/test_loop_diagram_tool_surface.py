"""A request's required tools are added to its surface only when the agent type may use them.

Regression coverage for evidence snapshot tools that a turn needs but its offered definitions
did not contain; change-gated tools never leak into read-only (diagnosis) turns.
"""

from __future__ import annotations

from app.agent.loops.request._loop_request_tool_surface import _ensure_named_tool_definitions

_SNAPSHOT_TOOL_NAMES = {
    "aws_topology_snapshot",
    "kubernetes_topology_snapshot",
    "code_structure_snapshot",
    "get_shape_library",
    "create_diagram",
}


def _definition_names(definitions: list[dict]) -> set[str]:
    return {
        str(definition.get("function", {}).get("name") or "").strip()
        for definition in definitions
        if isinstance(definition, dict)
    }


def test_ensure_named_tool_definitions_injects_code_structure_snapshot_for_diagnosis() -> None:
    definitions = _ensure_named_tool_definitions([], _SNAPSHOT_TOOL_NAMES, agent_type="diagnosis")
    names = _definition_names(definitions)
    assert "code_structure_snapshot" in names
    assert "aws_topology_snapshot" in names


def test_ensure_named_tool_definitions_injects_code_structure_snapshot_for_change() -> None:
    definitions = _ensure_named_tool_definitions([], _SNAPSHOT_TOOL_NAMES, agent_type="change")
    assert "code_structure_snapshot" in _definition_names(definitions)


def test_ensure_named_tool_definitions_keeps_existing_definitions_unchanged() -> None:
    existing = _ensure_named_tool_definitions([], {"create_diagram"}, agent_type="change")
    assert _ensure_named_tool_definitions(existing, {"create_diagram"}, agent_type="change") is existing


def test_repository_fetch_tool_is_change_gated_in_ensure() -> None:
    required = {*_SNAPSHOT_TOOL_NAMES, "prepare_bitbucket_repository"}
    change_definitions = _ensure_named_tool_definitions([], required, agent_type="change")
    diagnosis_definitions = _ensure_named_tool_definitions([], required, agent_type="diagnosis")
    assert "prepare_bitbucket_repository" in _definition_names(change_definitions)
    # Diagnosis turns stay read-only: the change-gated fetch tool must not leak.
    assert "prepare_bitbucket_repository" not in _definition_names(diagnosis_definitions)
