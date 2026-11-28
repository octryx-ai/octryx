"""One check library decides when a workflow's turn is done, in platform chat and at octryx-claude's Stop."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.workflow_checks.evidence import turn_evidence
from app.services.workflow_checks.library import evaluate_checks, failed_blocking, validate_checks
from app.services.workflow_runs.phase_validation import validate_phase_payload
from tests.workflow_checks_support import KNOWLEDGE_CHECKS

SEEDS = Path(__file__).resolve().parents[1] / "app/services/workflow_runs/seeds/phased_workflows.json"


def _outcomes(checks, evidence):
    return [result.outcome for result in evaluate_checks(checks, evidence)]


def test_every_check_type_is_closed_and_deterministic():
    history = [
        {"tool_name": "aws_topology_snapshot", "status": "success", "result": {"edges": [{"a": "b"}]}},
        {"tool_name": "create_diagram", "status": "success", "result": {"id": "d"}},
        {"tool_name": "web_search", "status": "error", "result": {"error": "x"}},
    ]
    evidence = turn_evidence(history, answer="The Diagram is ready",
                             answer_evidence={"cited_count": 0, "evidence_url_count": 2})
    checks = [
        {"type": "tool_called", "params": {"tools": ["aws_topology_snapshot", "create_diagram"]}},
        {"type": "tool_called", "params": {"tools": ["web_search"]}},
        {"type": "tool_not_called", "params": {"tools": ["web_search"]}},
        {"type": "evidence_count", "params": {"min_count": 2}},
        {"type": "artifact_created", "params": {"artifact_type": "diagram"}},
        {"type": "citations_present"},
        {"type": "answer_contains_any", "params": {"values": ["diagram"]}},
        {"type": "field_present", "params": {"tool": "aws_topology_snapshot", "field": "edges"}},
        {"type": "test_command_passed"},
        {"type": "judge"},
    ]
    assert _outcomes(checks, evidence) == [
        "passed", "failed", "failed", "passed", "passed", "failed", "passed", "passed", "not_applicable", "skipped",
    ]
    assert _outcomes([{"type": "citations_present"}], turn_evidence([])) == ["not_applicable"]
    assert _outcomes([{"type": "test_command_passed"}], turn_evidence([], verification_state="blocked")) == ["failed"]


def test_judge_is_never_blocking_and_unknown_types_are_refused():
    assert validate_checks(None) == []
    assert validate_checks(KNOWLEDGE_CHECKS) == []
    codes = {error["code"] for error in validate_checks([{"type": "regex"}, {"type": "judge", "blocking": True}])}
    assert codes == {"unknown_check_type", "judge_check_blocking"}
    results = evaluate_checks([{"type": "judge", "blocking": True}], turn_evidence([]))
    assert failed_blocking(results) == [] and results[0].blocking is False


def test_a_phase_with_invalid_checks_is_refused_on_save():
    payload = {
        "workflow_id": "w", "workflow_class": "knowledge_request",
        "workflow_contract": {"capability_class": "read_only", "checks": [{"type": "keyword_match"}]},
        "tool_policy": {"allowlist": ["knowledge_search"]}, "safety_constraints": {"diagnosis_mode": True},
    }
    result = validate_phase_payload(payload)
    assert "unknown_check_type" in {error["code"] for error in result["errors"]}


def test_every_shipped_phased_workflow_declares_valid_checks():
    for seed in json.loads(SEEDS.read_text()):
        for node in seed["definition"]["nodes"]:
            checks = (node.get("config") or {}).get("checks")
            if node.get("type") == "phase":
                checks = node["config"]["workflow_contract"].get("checks")
            assert validate_checks(checks) == [], (seed["key"], node["id"])


def test_steps_default_by_class_and_validate_their_mode():
    from app.services.workflow_checks.steps import step_checks, validate_steps, workflow_steps

    read_only = {"capability_class": "read_only", "source_steps": [
        {"tool": "knowledge_search", "evidence_label": "sources"},
        {"tool": "knowledge_read", "mode": "strict"},
        {"tool": "memory_recall", "required": False},
    ]}
    assert [step["mode"] for step in workflow_steps(read_only)] == ["guided", "strict", "guided"]
    assert [check["blocking"] for check in step_checks(read_only)] == [False, True]
    change = {"capability_class": "change", "source_steps": [{"tool": "run_test_suite"}]}
    assert workflow_steps(change)[0]["mode"] == "strict"
    assert validate_steps({"source_steps": [{"tool": "x", "mode": "loose"}]})[0]["code"] == "invalid_step_mode"


@pytest.mark.asyncio
async def test_instruction_get_without_a_key_needs_clarification(db):
    from app.tools.context import ToolContext
    from app.tools.instruction_tools import InstructionGetTool

    context = ToolContext(user_id="u", project_ids=[], roles=[], session_id="s", project_config={}, db=db)
    answer = await InstructionGetTool().execute({}, context)
    assert answer == {"state": "needs_clarification", "reason": "instruction_key_required"}
