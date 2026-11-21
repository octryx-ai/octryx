"""Coding quality gates over an evidence bundle: change plan, recorded checks, reviewer approval and policy."""

from __future__ import annotations

from typing import Any

from ....models import (
    WorkChangePlan,
    WorkItem,
)
from ..coding_serializers import (
    serialize_coding_pipeline_stage,
)
from ..jira_values import object_value
from ..plan_serializers import serialize_change_plan, serialize_change_unit
from .coding_gate_evidence import (
    RECORDED_GATE_KEYS,
    evaluate_recorded_gate,
    recorded_test_records,
)

BLOCKING_GATE_STATUSES = {"block", "failed", "missing"}
FAILING_STATUSES = {"failed", "failure", "error", "blocked", "declined", "rejected", "critical"}


def _quality_gates(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _gate_change_plan(bundle),
        *(_gate_recorded(bundle, key) for key in RECORDED_GATE_KEYS),
        _gate_reviewer_approval(bundle),
        _gate_policy(bundle),
    ]


def _gate_change_plan(bundle: dict[str, Any]) -> dict[str, Any]:
    """Decided by the latest plan version only: an earlier approval never covers a newer plan."""
    rows = bundle["change_plans"]  # newest version first
    if not rows:
        return _gate("change_plan", "missing", "No Change Plan evidence is attached.", {})
    latest_row = rows[0]
    latest = serialize_change_plan(latest_row)
    label = f"v{latest['version']}"
    if latest["status"] == "approved":
        stale_reason = _stale_change_plan_reason(bundle["item"], latest_row)
        if stale_reason:
            return _gate("change_plan", "block", stale_reason["message"], stale_reason)
        return _gate("change_plan", "pass", f"Latest Change Plan {label} is approved.", {"plan_id": latest["id"]})
    evidence = {"plan_id": latest["id"], "plan_status": latest["status"], "version": latest["version"]}
    earlier = next((row for row in rows[1:] if row.status == "approved"), None)
    note = ""
    if earlier is not None:
        evidence["earlier_approved_plan_id"] = earlier.id
        evidence["earlier_approved_version"] = earlier.version
        note = f" The earlier approval of v{earlier.version} does not cover the latest plan."
    if latest["status"] == "ready_for_review":
        return _gate(
            "change_plan",
            "review_required",
            f"Latest Change Plan {label} is ready for review and not approved yet.{note}",
            evidence,
        )
    # Not approvable as is (for example needs clarification or rejected): blocking, with the actual state.
    return _gate(
        "change_plan",
        "missing",
        f"No approved Change Plan. Latest plan {label} is {latest['status'].replace('_', ' ')}.{note}",
        evidence,
    )


def _stale_change_plan_reason(item: WorkItem, plan: WorkChangePlan | None) -> dict[str, Any] | None:
    if plan is None:
        return None
    source_fields = object_value(item.source_fields_json)
    if source_fields.get("requires_replan") or source_fields.get("source_evidence_stale"):
        return {
            "plan_id": plan.id,
            "code": "source_evidence_stale",
            "message": "Approved Change Plan is stale because linked source evidence changed after planning.",
            "source_evidence": {
                "external_replan_reason": source_fields.get("external_replan_reason"),
                "latest_source_stale_event": source_fields.get("latest_source_stale_event"),
            },
        }
    source_updated = item.last_source_updated_at
    plan_cutoff = plan.approved_at or plan.decided_at or plan.updated_at or plan.created_at
    if source_updated and plan_cutoff and source_updated > plan_cutoff:
        return {
            "plan_id": plan.id,
            "code": "source_changed_after_plan",
            "message": "Approved Change Plan is stale because the Jira source changed after plan approval.",
            "source_evidence": {
                "last_source_updated_at": source_updated.isoformat(),
                "plan_cutoff_at": plan_cutoff.isoformat(),
            },
        }
    return None


def _gate_recorded(bundle: dict[str, Any], key: str) -> dict[str, Any]:
    status, reason, evidence = evaluate_recorded_gate(
        key, bundle["recorded_gate_evidence"], planned_checks=_planned_check_count(bundle)
    )
    return _gate(key, status, reason, evidence)


def _planned_check_count(bundle: dict[str, Any]) -> int:
    """Planned checks (latest plan and active Change Units): intent, reported but never evidence."""
    plans = bundle["change_plans"]
    planned = len(plans[0].validation_plan_json or []) if plans else 0
    return planned + sum(len(unit.validation_commands_json or []) for unit in bundle["change_units"])


def _gate_reviewer_approval(bundle: dict[str, Any]) -> dict[str, Any]:
    result = bundle["reviewer_gate"]
    return _gate("reviewer_approval", result["status"], result["reason"], result["evidence"])


def _gate_policy(bundle: dict[str, Any]) -> dict[str, Any]:
    stages = [serialize_coding_pipeline_stage(stage) for stage in bundle["pipeline_stages"]]
    policy_stage = next((stage for stage in stages if "policy" in stage["stage_key"]), None)
    if policy_stage and policy_stage["status"] == "completed":
        return _gate("policy_status", "pass", "Policy stage completed.", {"stage": policy_stage})
    if policy_stage and policy_stage["status"] in {"policy_blocked", "failed"}:
        return _gate("policy_status", "block", "Policy stage is blocking.", {"stage": policy_stage})
    if policy_stage:
        return _gate(
            "policy_status",
            "review_required",
            "Policy stage exists but is not completed.",
            {"stage": policy_stage},
        )
    return _gate("policy_status", "missing", "No policy status evidence found.", {})


def _pr_summary(bundle: dict[str, Any], gates: list[dict[str, Any]]) -> dict[str, Any]:
    item: WorkItem = bundle["item"]
    units = [serialize_change_unit(unit) for unit in bundle["change_units"]]
    plans = [serialize_change_plan(plan) for plan in bundle["change_plans"]]
    latest_plan = plans[0] if plans else None
    gate_summary = _gate_summary(gates)
    return {
        "title": f"{item.source_key}: {item.title}",
        "status": gate_summary["status"],
        "request": latest_plan["understood_request"] if latest_plan else item.description or item.title,
        "implementation": [unit["scope"] or unit["repository_name"] for unit in units],
        "files": sorted({path for unit in units for path in unit["expected_paths"]}),
        "repositories": sorted({unit["repository_name"] for unit in units if unit["repository_name"]}),
        "branches": sorted({unit["branch_name"] for unit in units if unit["branch_name"]}),
        "tests": recorded_test_records(bundle["recorded_gate_evidence"]),
        "risks": [gate for gate in gates if gate["blocking"] or gate["status"] in {"review_required", "missing"}],
        # Current validated approvers only; commenters and override entries are not approvers.
        "reviewers": bundle["reviewer_gate"]["approvers"],
        # Every gate must pass: a gate that needs review is not ready either.
        "ready_to_open_pr": all(gate["status"] == "pass" for gate in gates),
    }


def _gate(key: str, status: str, reason: str, evidence: dict[str, Any]) -> dict[str, Any]:
    normalized = "block" if status in FAILING_STATUSES else status
    return {
        "key": key,
        "label": key.replace("_", " ").title(),
        "status": normalized,
        "blocking": normalized in BLOCKING_GATE_STATUSES,
        "reason": reason,
        "evidence": evidence,
    }


def _gate_summary(gates: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for gate in gates:
        counts[gate["status"]] = counts.get(gate["status"], 0) + 1
    blocking = sum(1 for gate in gates if gate["blocking"])
    if blocking:
        status = "blocked"
    elif counts.get("review_required") or counts.get("missing"):
        status = "review_required"
    else:
        status = "passed"
    return {"status": status, "total": len(gates), "blocking": blocking, "counts": counts}


def _dict_items(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in _as_list(value) if isinstance(item, dict)]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return [value]
