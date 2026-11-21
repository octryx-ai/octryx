from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ....models import WorkCodingPipelineStage

STATE_MACHINE_VERSION = "coding_execution_state_machine.v1"

CANONICAL_PHASES = (
    "prepared",
    "inspected",
    "edited",
    "validated",
    "diffed",
    "committed",
    "pr_created",
    "blocked",
    "declined",
    "completed",
)

PHASE_NEXT_ACTIONS: dict[str, dict[str, str]] = {
    "prepared": {
        "key": "prepare_workspace",
        "label": "Prepare the approved repository workspace and branch.",
    },
    "inspected": {
        "key": "inspect_scope",
        "label": "Inspect Jira evidence and the approved repository paths.",
    },
    "edited": {
        "key": "edit_or_block",
        "label": "Apply scoped changes or stop with a precise blocker.",
    },
    "validated": {
        "key": "run_validation",
        "label": "Run the approved local validation commands.",
    },
    "diffed": {
        "key": "inspect_diff",
        "label": "Inspect the diff and policy evidence before delivery.",
    },
    "committed": {
        "key": "commit_changes",
        "label": "Commit and push the approved branch.",
    },
    "pr_created": {
        "key": "create_pull_request",
        "label": "Open or update the pull request for human review.",
    },
    "blocked": {
        "key": "stop_blocked",
        "label": "Stop until the missing evidence or blocker is resolved.",
    },
    "declined": {
        "key": "restart_or_replan",
        "label": "Restart from a new plan or wait for human direction.",
    },
    "completed": {
        "key": "complete",
        "label": "Record closeout evidence and wait for human acceptance.",
    },
}

PHASE_REQUIRED_EVIDENCE: dict[str, list[str]] = {
    "prepared": ["workspace_prepared"],
    "inspected": ["scope_inspected"],
    "edited": ["changes_made or no_op"],
    "validated": ["validation_passed or no_op"],
    "diffed": ["diff_reviewed or no_op"],
    "committed": ["commit_created or no_op"],
    "pr_created": ["pull_request_created or no_op"],
    "blocked": ["blocker_reason"],
    "declined": ["decline_reason"],
    "completed": ["pull_request_created or no_op"],
}


def evaluate_coding_state_machine(
    stages: Iterable[WorkCodingPipelineStage],
    *,
    summary: dict[str, Any] | None = None,
    run_status: str | None = None,
) -> dict[str, Any]:
    stage_list = list(stages)
    summary_payload = dict(summary or {})
    execution_context = _object(summary_payload.get("execution_context"))
    blockers = _list_of_objects(execution_context.get("blockers"))
    stage_blockers = _stage_blockers(stage_list)
    evidence = _evidence_snapshot(stage_list, summary_payload)

    if run_status == "cancelled":
        return _snapshot("declined", "declined", evidence, blockers=[{"code": "run_cancelled"}])
    if blockers or stage_blockers:
        return _snapshot("blocked", "blocked", evidence, blockers=[*blockers, *stage_blockers])

    if _all_done(stage_list):
        if evidence["pull_request_created"] or evidence["no_op"]:
            return _snapshot("completed", "completed", evidence)
        return _snapshot(
            "blocked",
            "blocked",
            evidence,
            blockers=[
                {
                    "code": "delivery_evidence_required",
                    "message": "Completion requires pull-request evidence or explicit no-op evidence.",
                }
            ],
        )

    for phase, evidence_key in (
        ("prepared", "workspace_prepared"),
        ("inspected", "scope_inspected"),
        ("edited", "changes_made"),
        ("validated", "validation_passed"),
        ("diffed", "diff_reviewed"),
        ("committed", "commit_created"),
        ("pr_created", "pull_request_created"),
    ):
        if evidence["no_op"] and phase in {"edited", "validated", "diffed", "committed", "pr_created"}:
            continue
        if not evidence[evidence_key]:
            return _snapshot(phase, "running", evidence)

    return _snapshot("completed", "completed", evidence)


def _snapshot(
    phase: str,
    status: str,
    evidence: dict[str, Any],
    *,
    blockers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "version": STATE_MACHINE_VERSION,
        "phase": phase,
        "status": status,
        "canonical_phases": list(CANONICAL_PHASES),
        "required_evidence": PHASE_REQUIRED_EVIDENCE[phase],
        "next_action": PHASE_NEXT_ACTIONS[phase],
        "evidence": evidence,
        "blockers": blockers or [],
    }


def _evidence_snapshot(stages: list[WorkCodingPipelineStage], summary: dict[str, Any]) -> dict[str, Any]:
    stage_by_key = {stage.stage_key: stage for stage in stages}
    evidence_items = [entry for stage in stages for entry in _list_of_objects(stage.evidence_json)]
    output_items = [_object(stage.outputs_json) for stage in stages]
    workspaces = _list_of_objects(summary.get("workspaces"))
    return {
        "workspace_prepared": bool(workspaces)
        or _stage_done(stage_by_key, "branch_worktree")
        or _has_kind(evidence_items, {"workspace_prepared", "branch_prepared"}),
        "scope_inspected": _stage_done(stage_by_key, "context_collection")
        or _has_kind(evidence_items, {"scope_inspected", "source_inspected", "repo_inspected"}),
        "changes_made": _stage_done(stage_by_key, "implementation")
        or _has_any_key(output_items, {"changed_files", "patches", "files_changed", "edits"}),
        "validation_passed": _stage_done(stage_by_key, "local_validation")
        or _has_kind(evidence_items, {"validation", "validation_passed", "test_run"}),
        "diff_reviewed": _stage_done(stage_by_key, "diff_review")
        or _has_kind(evidence_items, {"diff_review", "diff_reviewed", "git_diff"}),
        "commit_created": _has_any_key(output_items, {"commit", "commits", "commit_sha", "commit_url"})
        or _has_kind(evidence_items, {"commit", "git_commit"}),
        "pull_request_created": _has_any_key(
            output_items,
            {"pull_request", "pull_requests", "pr", "pr_url", "pull_request_url", "pull_request_id"},
        )
        or _has_kind(evidence_items, {"pull_request", "pr_created", "pull_request_created"}),
        "no_op": _has_any_key(output_items, {"no_op", "no_op_reason"})
        or _has_kind(evidence_items, {"no_op", "no_changes_required"}),
    }


def _stage_blockers(stages: list[WorkCodingPipelineStage]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for stage in stages:
        if stage.status in {"failed", "policy_blocked"}:
            blockers.append(
                {
                    "code": f"stage_{stage.status}",
                    "stage_key": stage.stage_key,
                    "message": f"Stage {stage.stage_key} is {stage.status}.",
                }
            )
    return blockers


def _all_done(stages: list[WorkCodingPipelineStage]) -> bool:
    return bool(stages) and all(stage.status in {"completed", "skipped"} for stage in stages)


def _stage_done(stage_by_key: dict[str, WorkCodingPipelineStage], key: str) -> bool:
    stage = stage_by_key.get(key)
    return bool(stage and stage.status in {"completed", "skipped"})


def _has_kind(items: list[dict[str, Any]], kinds: set[str]) -> bool:
    return any(str(item.get("kind") or "").strip() in kinds for item in items)


def _has_any_key(items: list[dict[str, Any]], keys: set[str]) -> bool:
    for item in items:
        if any(key in item and item.get(key) not in (None, "", [], {}) for key in keys):
            return True
    return False


def _object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_of_objects(value: Any) -> list[dict[str, Any]]:
    return [dict(entry) for entry in value or [] if isinstance(entry, dict)]
