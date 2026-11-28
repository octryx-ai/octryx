"""Recorded Coding quality-gate evidence."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.secure_work.coding.coding_gate_evidence import (
    collect_recorded_gate_evidence,
    evaluate_recorded_gate,
)

T0 = datetime(2026, 10, 4, 12, 0, 0)


def _event(gate_results, *, event_type="local_validation", metadata=None, minutes=0, summary=""):
    return SimpleNamespace(
        id=f"event-{event_type}-{minutes}-{len(str(gate_results))}",
        event_type=event_type,
        metadata_json=metadata or {},
        gate_results_json=gate_results,
        summary=summary,
        created_at=T0 + timedelta(minutes=minutes),
    )


def _finding(event_status, *, status="current", job="acme-orders/api-main", branch="main", minutes=0, gate_results=None,
             finding_id=None, provider="provider-a", commit="sha-1", current_for_commit=True):
    return SimpleNamespace(
        id=finding_id or f"finding-{provider}-{job}-{branch}-{commit}-{minutes}",
        status=status,
        current_for_commit=current_for_commit,
        event_status=event_status,
        provider_config_id=provider,
        job_name=job,
        branch_name=branch,
        commit_sha=commit,
        build_number=str(minutes),
        created_at=T0 + timedelta(minutes=minutes),
        gate_results_json=gate_results or [],
    )


def _stage(stage_key, status):
    return SimpleNamespace(id=f"stage-{stage_key}", stage_key=stage_key, status=status, completed_at=T0, updated_at=T0)


def _gate(key, *, audit_events=(), findings=(), stages=(), planned_checks=0):
    bundle = {
        "audit_events": list(audit_events),
        "cicd_findings": list(findings),
        "pipeline_stages": list(stages),
    }
    status, reason, evidence = evaluate_recorded_gate(key, collect_recorded_gate_evidence(bundle), planned_checks=planned_checks)
    return status, reason, evidence


def test_plan_only_password_command_is_missing_not_pass():
    # Only a planned `pytest tests/test_password.py`; "password" contains "pass".
    status, reason, evidence = _gate("local_tests", planned_checks=1)
    assert status == "missing"
    assert "1 planned check" in reason and "not results" in reason
    assert evidence["matches"] == []


@pytest.mark.parametrize("key", ["local_tests", "lint", "dependency_audit", "trivy_security_scan", "ci_status"])
def test_free_text_and_command_only_records_never_select_or_pass_a_gate(key):
    noisy = _event([], summary="password compass successor unblocked pytest ruff trivy npm audit pipeline passed")
    command_only = _event([{"command": "pytest tests/test_password.py", "status": "passed"},
                           {"name": "backend-ci pipeline", "status": "success"}], minutes=1)
    status, _, evidence = _gate(key, audit_events=[noisy, command_only])
    assert status == "missing"
    assert evidence["matches"] == []


@pytest.mark.parametrize("token", ["completed", "approved", "merged", "pending", "running", "", None, 1])
def test_non_outcome_status_tokens_are_inconclusive_for_a_named_gate(token):
    status, _, _ = _gate("lint", audit_events=[_event([{"key": "lint", "status": token}])])
    assert status == "review_required"


def test_malformed_and_unknown_records_are_not_dropped_into_a_pass():
    event = _event([
        {"key": "lint", "status": "passed"},
        {"key": "lint"},
        "lint passed",
        {"key": "unit_tests", "status": "passed"},
    ])
    status, _, evidence = _gate("lint", audit_events=[event])
    assert status == "review_required", "an entry without an outcome keeps the gate open"
    assert evidence["recorded_count"] == 2


def test_explicit_gate_results_pass():
    event = _event([{"key": "dependency_audit", "status": "passed"}, {"key": "reviewer_approval", "status": "pass"},
                    {"key": "trivy_security_scan", "status": "SUCCESS"}])
    assert _gate("dependency_audit", audit_events=[event])[0] == "pass"
    assert _gate("trivy_security_scan", audit_events=[event])[0] == "pass"
    assert _gate("local_tests", audit_events=[event])[0] == "missing", "an explicit result names only its own gate"


def test_quality_gate_evaluation_snapshots_are_ignored():
    snapshot = _event([{"key": "local_tests", "status": "pass"}], event_type="quality_gate_evaluation")
    assert _gate("local_tests", audit_events=[snapshot])[0] == "missing"


def test_a_pass_never_erases_a_different_or_unidentified_failure():
    failed_then_passed = [
        _event([{"key": "local_tests", "status": "failed"}], minutes=1),
        _event([{"key": "local_tests", "status": "passed"}], minutes=2),
    ]
    status, reason, _ = _gate("local_tests", audit_events=failed_then_passed)
    assert status == "block", "without a producer identity both records are kept"
    assert "1 recorded local tests result failed" in reason


def test_a_rerun_of_the_same_ci_run_collapses_to_the_latest_build():
    assert _gate("ci_status", findings=[_finding("failed", minutes=1), _finding("passed", minutes=2)])[0] == "pass"
    assert _gate("ci_status", findings=[_finding("passed", minutes=1), _finding("failed", minutes=2)])[0] == "block"


def test_identity_collisions_keep_records_apart_conservatively():
    other_branch = [_finding("failed", branch="release", minutes=1), _finding("passed", branch="main", minutes=2)]
    assert _gate("ci_status", findings=other_branch)[0] == "block", "another branch is another scope"
    other_job = [_finding("failed", job="api-lint", minutes=1), _finding("passed", job="api-test", minutes=2)]
    assert _gate("ci_status", findings=other_job)[0] == "block", "another job is another check"
    no_branch = [_finding("failed", branch=None, minutes=1), _finding("passed", branch=None, minutes=2)]
    assert _gate("ci_status", findings=no_branch)[0] == "block", "no stable scope, so no collapse"


def test_root_counterexample_another_provider_is_another_check():
    findings = [
        _finding("failed", provider="provider-a", job="build", minutes=1),
        _finding("passed", provider="provider-b", job="build", minutes=2),
    ]
    assert _gate("ci_status", findings=findings)[0] == "block"


@pytest.mark.parametrize("missing", ["provider", "job", "branch", "commit"])
def test_a_missing_identity_part_keeps_records_separate(missing):
    later_pass = {"provider": "provider-a", "job": "build", "branch": "main", "commit": "sha-1"}
    later_pass[missing] = ""
    findings = [_finding("failed", job="build", minutes=1), _finding("passed", minutes=2, **later_pass)]
    assert _gate("ci_status", findings=findings)[0] == "block"


def test_commit_boundaries_are_not_crossed_but_reruns_of_one_commit_are():
    other_commit = [_finding("failed", commit="sha-1", minutes=1), _finding("passed", commit="sha-2", minutes=2)]
    assert _gate("ci_status", findings=other_commit)[0] == "block", "a newer commit is not a rerun of the failed one"
    rerun = [_finding("failed", commit="sha-2", minutes=1), _finding("passed", commit="sha-2", minutes=3)]
    assert _gate("ci_status", findings=rerun)[0] == "pass", "build 3 reran the same commit"


def test_a_timestamp_tie_never_lets_a_pass_hide_a_failure():
    tie = [_finding("failed", minutes=5, finding_id="a"), _finding("passed", minutes=5, finding_id="b")]
    assert _gate("ci_status", findings=tie)[0] == "block"
    assert _gate("ci_status", findings=list(reversed(tie)))[0] == "block"


def test_runs_not_current_for_their_commit_are_excluded():
    old = _finding("failed", current_for_commit=False, minutes=1)
    assert _gate("ci_status", findings=[old])[0] == "missing"
    assert _gate("ci_status", findings=[old, _finding("passed", minutes=2, commit="sha-2")])[0] == "pass"


def test_root_counterexample_conflicting_entries_in_one_record_keep_the_failure():
    finding = _finding("passed", gate_results=[{"key": "lint", "status": "failed"}, {"key": "lint", "status": "passed"}])
    assert _gate("lint", findings=[finding])[0] == "block"
    event = _event([{"key": "lint", "status": "passed"}, {"key": "lint", "status": "failed"}])
    assert _gate("lint", audit_events=[event])[0] == "block"
    rerun_with_entry = [
        _finding("passed", minutes=1, gate_results=[{"key": "dependency_audit", "status": "failed"}]),
        _finding("passed", minutes=2, gate_results=[{"key": "dependency_audit", "status": "passed"}]),
    ]
    assert _gate("dependency_audit", findings=rerun_with_entry)[0] == "block", "a gate key is not a check identity"


def test_stale_ci_is_excluded_on_every_path():
    stale = _finding("failed", status="stale_ignored", minutes=1, finding_id="stale-1")
    mirror_event = _event(
        [{"key": "ci_status", "status": "block"}],
        event_type="cicd_finding",
        metadata={"source": "cicd_findings", "finding_status": "stale_ignored"},
    )
    assert _gate("ci_status", findings=[stale], audit_events=[mirror_event])[0] == "missing"
    current = _finding("passed", minutes=2)
    assert _gate("ci_status", findings=[stale, current], audit_events=[mirror_event])[0] == "pass"


def test_ci_status_comes_from_the_finding_outcome_and_other_gates_from_its_explicit_results():
    finding = _finding(
        "running",
        gate_results=[{"key": "ci_status", "status": "pass"}, {"key": "dependency_audit", "status": "passed"}],
    )
    assert _gate("ci_status", findings=[finding])[0] == "review_required", "a running build is not a pass"
    assert _gate("dependency_audit", findings=[finding])[0] == "pass"


def test_stage_completion_never_passes_but_a_failed_stage_blocks():
    assert _gate("local_tests", stages=[_stage("local_validation", "completed")])[0] == "missing"
    assert _gate("ci_status", stages=[_stage("ci_cd", "completed")])[0] == "missing"
    assert _gate("local_tests", stages=[_stage("local_validation", "failed")])[0] == "block"
    assert _gate("lint", stages=[_stage("local_validation", "policy_blocked")])[0] == "block"
    assert _gate("ci_status", stages=[_stage("ci_cd", "failed")])[0] == "block"
