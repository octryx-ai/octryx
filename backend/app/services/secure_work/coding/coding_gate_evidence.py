"""Recorded Coding quality-gate evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkCicdFinding

RECORDED_GATE_KEYS = ("local_tests", "lint", "dependency_audit", "trivy_security_scan", "ci_status")
PASS_TOKENS = frozenset({"pass", "passed", "success", "succeeded", "ok"})
FAIL_TOKENS = frozenset(
    {"fail", "failed", "failure", "error", "errored", "block", "blocked", "timed_out", "timeout", "unstable"}
)
CURRENT_FINDING_STATUS = "current"
STALE_FINDING_STATUS = "stale_ignored"
SNAPSHOT_EVENT_TYPE = "quality_gate_evaluation"
CICD_FINDING_EVENT_SOURCE = "cicd_findings"
FAILED_STAGE_STATUSES = frozenset({"failed", "policy_blocked"})
STAGE_GATES = {"local_validation": ("local_tests", "lint"), "ci_cd": ("ci_status",)}
MAX_LISTED_RECORDS = 10

GATE_LABELS = {
    "local_tests": "local tests",
    "lint": "lint",
    "dependency_audit": "dependency audit",
    "trivy_security_scan": "security scan",
    "ci_status": "CI/CD",
}


@dataclass(frozen=True)
class GateRecord:
    gate: str
    outcome: str  # "pass" | "fail" | "inconclusive"
    source: str
    ref: dict[str, Any]
    # Records with the same identity are the same check; only the latest of them counts.
    identity: tuple[str, ...] | None = None
    recorded_at: str = ""


@dataclass
class RecordedGateEvidence:
    records: list[GateRecord] = field(default_factory=list)


async def load_native_ci_findings(db: AsyncSession, work_item_id: str) -> list[WorkCicdFinding]:
    return list(
        (
            await db.execute(
                select(WorkCicdFinding)
                .where(WorkCicdFinding.work_item_id == work_item_id)
                .order_by(WorkCicdFinding.created_at.asc(), WorkCicdFinding.id.asc())
            )
        ).scalars()
    )


def outcome_from_status(value: Any) -> str:
    token = value.strip().lower() if isinstance(value, str) else ""
    if token in PASS_TOKENS:
        return "pass"
    if token in FAIL_TOKENS:
        return "fail"
    return "inconclusive"


def _explicit_gate(entry: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    for name in fields:
        value = entry.get(name)
        if isinstance(value, str) and value.strip() in RECORDED_GATE_KEYS:
            return value.strip()
    return None


def _iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else ""


def collect_recorded_gate_evidence(bundle: dict[str, Any]) -> RecordedGateEvidence:
    evidence = RecordedGateEvidence()
    _collect_audit_event_results(bundle.get("audit_events") or [], evidence)
    _collect_native_findings(list(bundle.get("cicd_findings") or []), evidence)
    _collect_failed_stages(bundle.get("pipeline_stages") or [], evidence)
    return evidence


def _collect_audit_event_results(events: list[Any], evidence: RecordedGateEvidence) -> None:
    for event in events:
        metadata = event.metadata_json if isinstance(event.metadata_json, dict) else {}
        # Snapshots repeat earlier evaluations; CI mirror events repeat native findings.
        if event.event_type == SNAPSHOT_EVENT_TYPE or metadata.get("source") == CICD_FINDING_EVENT_SOURCE:
            continue
        entries = event.gate_results_json if isinstance(event.gate_results_json, list) else []
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            gate = _explicit_gate(entry, ("key",))
            if gate is None:
                continue
            evidence.records.append(
                GateRecord(
                    gate=gate,
                    outcome=outcome_from_status(entry.get("status")),
                    source="audit_event",
                    ref={"audit_event_id": event.id, "event_type": event.event_type, "status": entry.get("status"),
                         "index": index},
                    recorded_at=_iso(event.created_at),
                )
            )


def _collect_native_findings(findings: list[Any], evidence: RecordedGateEvidence) -> None:
    for finding in findings:
        # Current only: stale_ignored and runs the producer marked as not current for their commit.
        if finding.status != CURRENT_FINDING_STATUS or finding.current_for_commit is False:
            continue
        ref = {
            "finding_id": finding.id,
            "provider_config_id": finding.provider_config_id,
            "job_name": finding.job_name,
            "branch_name": finding.branch_name,
            "commit_sha": finding.commit_sha,
            "build_number": finding.build_number,
            "event_status": finding.event_status,
        }
        evidence.records.append(
            GateRecord(
                gate="ci_status",
                outcome=outcome_from_status(finding.event_status),
                source="ci_finding",
                ref=ref,
                identity=_ci_run_identity(finding),
                recorded_at=_iso(finding.created_at),
            )
        )
        for entry in finding.gate_results_json if isinstance(finding.gate_results_json, list) else []:
            if not isinstance(entry, dict):
                continue
            gate = _explicit_gate(entry, ("key",))
            # ci_status is decided by the finding's own event_status above.
            if gate is None or gate == "ci_status":
                continue
            # No identity: a gate key is not a check identity, and several entries in one finding
            # (even for the same gate) are kept side by side, so a failed entry is never overwritten.
            evidence.records.append(
                GateRecord(
                    gate=gate,
                    outcome=outcome_from_status(entry.get("status")),
                    source="ci_finding_gate_result",
                    ref={**ref, "status": entry.get("status")},
                    recorded_at=_iso(finding.created_at),
                )
            )


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _ci_run_identity(finding: Any) -> tuple[str, ...] | None:
    # Builds of the same tuple are reruns of that check; any missing part means no identity.
    parts = (
        _text(finding.provider_config_id),
        _text(finding.job_name),
        _text(finding.branch_name),
        _text(finding.commit_sha),
    )
    return ("ci_run", *parts) if all(parts) else None


def _collect_failed_stages(stages: list[Any], evidence: RecordedGateEvidence) -> None:
    for stage in stages:
        gates = STAGE_GATES.get(stage.stage_key)
        if not gates or stage.status not in FAILED_STAGE_STATUSES:
            continue
        for gate in gates:
            evidence.records.append(
                GateRecord(
                    gate=gate,
                    outcome="fail",
                    source="pipeline_stage",
                    ref={"stage_id": stage.id, "stage_key": stage.stage_key, "status": stage.status},
                    recorded_at=_iso(stage.completed_at or stage.updated_at),
                )
            )


def _effective_records(records: list[GateRecord]) -> list[GateRecord]:
    latest: dict[tuple[str, ...], list[GateRecord]] = {}
    kept: list[GateRecord] = []
    for record in records:
        # Only a stable producer identity proves the same check run; anything else is kept
        if record.identity is None or not record.recorded_at:
            kept.append(record)
            continue
        current = latest.get(record.identity)
        if current is None or record.recorded_at > current[0].recorded_at:
            latest[record.identity] = [record]
        # A tie keeps every tied record, so a pass never hides a failure
        elif record.recorded_at == current[0].recorded_at:
            current.append(record)
    return kept + [record for group in latest.values() for record in group]


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def evaluate_recorded_gate(
    key: str,
    evidence: RecordedGateEvidence,
    *,
    planned_checks: int,
) -> tuple[str, str, dict[str, Any]]:
    label = GATE_LABELS[key]
    records = _effective_records([record for record in evidence.records if record.gate == key])
    failed = [record for record in records if record.outcome == "fail"]
    open_ = [record for record in records if record.outcome == "inconclusive"]
    details = {
        "matches": [{"source": record.source, "outcome": record.outcome, **record.ref} for record in records][
            :MAX_LISTED_RECORDS
        ],
        "recorded_count": len(records),
        "planned_checks": planned_checks,
    }
    if failed:
        return "block", f"{_plural(len(failed), 'recorded ' + label + ' result')} failed.", details
    if open_:
        return (
            "review_required",
            f"{_plural(len(open_), 'recorded ' + label + ' result')} without a pass or fail outcome.",
            details,
        )
    if records:
        return "pass", f"{_plural(len(records), 'recorded ' + label + ' result')}, all passed.", details
    suffix = f" ({_plural(planned_checks, 'planned check')} are not results)" if planned_checks else ""
    return "missing", f"No recorded {label} result names this gate{suffix}.", details


def recorded_test_records(evidence: RecordedGateEvidence) -> list[dict[str, Any]]:
    local = [record for record in evidence.records if record.gate in {"local_tests", "lint"}]
    return [
        {"gate": record.gate, "source": record.source, "outcome": record.outcome, **record.ref}
        for record in _effective_records(local)
    ][:12]
