"""Dispatch guard: code-structure diagrams require snapshot evidence first."""

from __future__ import annotations

from app.services.turn_tool_guards_code_structure import (
    code_structure_diagram_evidence_guard_result,
    enforce_code_structure_snapshot_full_scope,
)

_CODE_STRUCTURE_SNAPSHOT_CONTEXT = {
    "request_analysis": {
        "workflow_contract": {
            "workflow_id": "generic_diagram",
            "workflow_class": "code_structure_diagram_request",
            "diagram_source": "code_structure_snapshot",
            "developer_diagram_type": "uml_class",
        }
    }
}


def _snapshot_history_item(*, nodes: int, error: str | None = None) -> dict:
    result: dict = {
        "diagram_brief": {
            "selected_nodes": [{"ref": f"class:C{index}"} for index in range(nodes)],
            "selected_edges": [],
        }
    }
    if error:
        result = {"error": error}
    return {"tool_name": "code_structure_snapshot", "result": result}


def test_guard_blocks_create_diagram_without_snapshot_evidence() -> None:
    guard = code_structure_diagram_evidence_guard_result(
        tool_name="create_diagram",
        tool_args={"xml": "<mxCell/>"},
        turn_tool_history=[],
        context_snapshot=_CODE_STRUCTURE_SNAPSHOT_CONTEXT,
    )
    assert guard is not None
    assert guard["guardrail"] == "code_structure_diagram_evidence_required"
    assert "prepare_bitbucket_repository" in guard["error"]


def test_guard_blocks_when_snapshot_errored_or_empty() -> None:
    errored = code_structure_diagram_evidence_guard_result(
        tool_name="create_diagram",
        tool_args={},
        turn_tool_history=[_snapshot_history_item(nodes=0, error="no matching source files")],
        context_snapshot=_CODE_STRUCTURE_SNAPSHOT_CONTEXT,
    )
    empty = code_structure_diagram_evidence_guard_result(
        tool_name="append_diagram",
        tool_args={},
        turn_tool_history=[_snapshot_history_item(nodes=0)],
        context_snapshot=_CODE_STRUCTURE_SNAPSHOT_CONTEXT,
    )
    assert errored is not None
    assert empty is not None


def test_guard_allows_create_diagram_with_snapshot_evidence() -> None:
    guard = code_structure_diagram_evidence_guard_result(
        tool_name="create_diagram",
        tool_args={},
        turn_tool_history=[_snapshot_history_item(nodes=3)],
        context_snapshot=_CODE_STRUCTURE_SNAPSHOT_CONTEXT,
    )
    assert guard is None


def test_guard_ignores_non_code_structure_contracts_and_other_tools() -> None:
    aws_context = {
        "request_analysis": {
            "workflow_contract": {
                "workflow_id": "generic_diagram",
                "diagram_source": "aws_topology_snapshot",
            }
        }
    }
    assert (
        code_structure_diagram_evidence_guard_result(
            tool_name="create_diagram",
            tool_args={},
            turn_tool_history=[],
            context_snapshot=aws_context,
        )
        is None
    )
    assert (
        code_structure_diagram_evidence_guard_result(
            tool_name="code_structure_snapshot",
            tool_args={},
            turn_tool_history=[],
            context_snapshot=_CODE_STRUCTURE_SNAPSHOT_CONTEXT,
        )
        is None
    )


def test_full_scope_enforcer_clears_paths_and_raises_bounds() -> None:
    args, trace = enforce_code_structure_snapshot_full_scope(
        tool_name="code_structure_snapshot",
        tool_args={"paths": ["terraform/base"], "languages": ["terraform"], "max_symbols": 60},
        context_snapshot=_CODE_STRUCTURE_SNAPSHOT_CONTEXT,
    )
    assert "paths" not in args
    assert args["max_symbols"] == 400
    assert args["max_files"] == 2000
    # the language filter is a declared evidence choice, never touched
    assert args["languages"] == ["terraform"]
    assert trace is not None
    assert trace["rule"] == "code_structure_snapshot_full_scope"
    assert trace["dropped_paths"] == ["terraform/base"]
    assert trace["previous_max_symbols"] == 60


def test_full_scope_enforcer_only_applies_to_evidence_bound_contracts() -> None:
    aws_context = {
        "request_analysis": {"workflow_contract": {"diagram_source": "aws_topology_snapshot"}}
    }
    args, trace = enforce_code_structure_snapshot_full_scope(
        tool_name="code_structure_snapshot",
        tool_args={"paths": ["src"]},
        context_snapshot=aws_context,
    )
    assert args == {"paths": ["src"]}
    assert trace is None
    args, trace = enforce_code_structure_snapshot_full_scope(
        tool_name="grep_workspace",
        tool_args={"paths": ["src"]},
        context_snapshot=_CODE_STRUCTURE_SNAPSHOT_CONTEXT,
    )
    assert args == {"paths": ["src"]}
    assert trace is None


def test_guard_respects_disabled_rule() -> None:
    guard = code_structure_diagram_evidence_guard_result(
        tool_name="create_diagram",
        tool_args={},
        turn_tool_history=[],
        context_snapshot=_CODE_STRUCTURE_SNAPSHOT_CONTEXT,
        exec_policy_config={
            "agent_guard_rules": [
                {
                    "id": "code_structure_diagram_evidence_required",
                    "enabled": False,
                }
            ]
        },
    )
    assert guard is None
