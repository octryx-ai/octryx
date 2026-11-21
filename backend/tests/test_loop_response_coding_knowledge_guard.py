"""The coding-progress guard must not treat a knowledge/evidence turn as a
coding turn, even if the capability mode resolved to "change" (benchmark
dev_cicd: a knowledge_request answer was killed for mentioning pipeline steps)."""

from __future__ import annotations

from app.agent.loops.response._loop_response_coding import _is_knowledge_evidence_turn


def test_knowledge_request_turn_is_detected():
    snapshot = {"request_analysis": {"workflow_contract": {"workflow_id": "knowledge_request"}}}
    assert _is_knowledge_evidence_turn(snapshot) is True


def test_coding_workflow_is_not_a_knowledge_turn():
    snapshot = {"request_analysis": {"workflow_contract": {"workflow_id": "coding_change_tdd"}}}
    assert _is_knowledge_evidence_turn(snapshot) is False


def test_missing_or_malformed_snapshot_is_safe():
    assert _is_knowledge_evidence_turn({}) is False
    assert _is_knowledge_evidence_turn({"request_analysis": None}) is False
    assert _is_knowledge_evidence_turn({"request_analysis": {"workflow_contract": {}}}) is False
