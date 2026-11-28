from __future__ import annotations

from app.models import WorkCodingPipelineStage
from app.services.secure_work.coding.coding_state_machine import evaluate_coding_state_machine


def _stage(
    key: str,
    status: str,
    *,
    evidence: list[dict] | None = None,
    outputs: dict | None = None,
) -> WorkCodingPipelineStage:
    return WorkCodingPipelineStage(
        run_id="run-1",
        stage_key=key,
        label=key,
        stage_order=0,
        status=status,
        evidence_json=evidence or [],
        outputs_json=outputs or {},
        required=True,
        updated_by="user-1",
    )


def test_coding_state_machine_requires_inspection_after_workspace_preparation():
    snapshot = evaluate_coding_state_machine(
        [
            _stage("intake", "ready"),
            _stage("context_collection", "pending"),
        ],
        summary={"workspaces": [{"id": "workspace-1"}]},
        run_status="running",
    )

    assert snapshot["phase"] == "inspected"
    assert snapshot["status"] == "running"
    assert snapshot["next_action"]["key"] == "inspect_scope"
    assert snapshot["required_evidence"] == ["scope_inspected"]


def test_coding_state_machine_blocks_completion_without_delivery_evidence():
    snapshot = evaluate_coding_state_machine(
        [
            _stage("intake", "completed"),
            _stage("context_collection", "completed"),
            _stage("implementation", "completed", outputs={"commits": 1}),
            _stage("local_validation", "completed"),
            _stage("diff_review", "completed"),
            _stage("acceptance_closeout", "completed"),
        ],
        summary={"workspaces": [{"id": "workspace-1"}]},
        run_status="completed",
    )

    assert snapshot["phase"] == "blocked"
    assert snapshot["status"] == "blocked"
    assert snapshot["blockers"][0]["code"] == "delivery_evidence_required"


def test_coding_state_machine_completes_with_pull_request_evidence():
    snapshot = evaluate_coding_state_machine(
        [
            _stage("intake", "completed"),
            _stage("context_collection", "completed"),
            _stage("implementation", "completed", outputs={"commits": 1}),
            _stage("local_validation", "completed"),
            _stage("diff_review", "completed"),
            _stage("acceptance_closeout", "completed", outputs={"pr_url": "https://bitbucket/pr/10"}),
        ],
        summary={"workspaces": [{"id": "workspace-1"}]},
        run_status="completed",
    )

    assert snapshot["phase"] == "completed"
    assert snapshot["status"] == "completed"
    assert snapshot["evidence"]["pull_request_created"] is True


def test_coding_state_machine_accepts_explicit_no_op_evidence():
    snapshot = evaluate_coding_state_machine(
        [
            _stage("intake", "completed"),
            _stage("context_collection", "completed"),
            _stage("implementation", "completed", outputs={"no_op_reason": "Already in requested state."}),
            _stage("local_validation", "skipped", evidence=[{"kind": "no_op"}]),
            _stage("acceptance_closeout", "completed"),
        ],
        summary={"workspaces": [{"id": "workspace-1"}]},
        run_status="completed",
    )

    assert snapshot["phase"] == "completed"
    assert snapshot["evidence"]["no_op"] is True


def test_coding_state_machine_surfaces_policy_blocker():
    snapshot = evaluate_coding_state_machine(
        [
            _stage("intake", "completed"),
            _stage("policy_preflight", "policy_blocked"),
        ],
        summary={"execution_context": {"blockers": [{"code": "approved_paths_required"}]}},
        run_status="policy_blocked",
    )

    assert snapshot["phase"] == "blocked"
    assert snapshot["next_action"]["key"] == "stop_blocked"
    assert {blocker["code"] for blocker in snapshot["blockers"]} == {
        "approved_paths_required",
        "stage_policy_blocked",
    }
