"""In a run the tool scope and the session tool cache come from the session's run, and a phase turn pauses or completes by the evidence families for its target."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.services.workflow_checks import evidence_families as families
from app.services.workflow_checks.evidence_families import (
    OK,
    UNAVAILABLE,
    evidence_envelope,
    with_envelope,
)
from app.services.workflow_checks.library import (
    FAILED,
    PASSED,
    TurnEvidence,
    evaluate_check,
    validate_checks,
)
from tests.incident_evidence_families_support import IN_WINDOW, SCOPE, WINDOW, _check, _use
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

# --- a phase turn end to end: unavailable pauses, no loop ---------------------------------------------------------


def _families_definition(check: dict) -> dict:
    from tests.phased_workflow_fixtures import PHASE

    phase = copy.deepcopy(PHASE)
    phase["workflow_contract"]["checks"] = [check]
    phase["tool_policy"]["allowlist"] = ["query_prometheus", "list_failed_pods", "knowledge_search"]
    return {
        "execution_kind": "phased",
        "nodes": [{"id": "start", "type": "start"},
                  {"id": "evidence", "type": "phase", "label": "Evidence", "config": phase},
                  {"id": "done", "type": "outcome", "config": {"outcome": "done"}}],
        "edges": [{"id": "1", "source_node_id": "start", "target_node_id": "evidence"},
                  {"id": "2", "source_node_id": "evidence", "target_node_id": "done"}],
    }


def _history(status: str, reason: str = "") -> dict:
    envelope = evidence_envelope("metrics", status, target_id="checkout", namespace="shop", window=IN_WINDOW,
                                 count=1 if status == OK else 0, reason=reason)
    result = with_envelope({"error": reason} if reason else {"instant_result": {"result": [{}]}}, envelope)
    return {"tool_name": "query_prometheus", "status": "success", "result": result}


async def _phased_run(db, check: dict):
    from app.services.workflow_runs.binding import run_turn_resolution
    from app.services.workflow_runs.records import new_chat_session, start_run
    from tests.phased_workflow_fixtures import admin_user, publish_phased, run_workspace

    admin = await admin_user(db)
    key = await publish_phased(db, _families_definition(check))
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=key, project_id=workspace_id, session=session)
    resolution = await run_turn_resolution(db, session, user_message="Collect.")
    return run, session, resolution


# --- the session tool cache (contract G12) ------------------------------------------------------------------------




@pytest.mark.asyncio
async def test_a_phase_turn_with_only_unavailable_metrics_pauses_evidence_unresolved(db):
    from tests.test_workflow_run_tdd_evidence import phase_turn_with_history

    run, session, resolution = await _phased_run(db, _check(from_target=True))
    run.context = {**dict(run.context or {}), "alert_target": {"id": "checkout", "required_families": ["metrics"],
                                                               "kubernetes": {"namespace": "shop"}},
                   "alert": {"window": WINDOW}}
    await db.commit()

    # The phase turn's own checks read the run's alert scope (``_loop_workflow_checks._evaluate``).
    await phase_turn_with_history(db, session.id, resolution, [_history(UNAVAILABLE, "prometheus_http_500")])
    await db.refresh(run)
    assert (run.status, run.pause_reason, run.current_node_id) == ("paused", "evidence_unresolved", "evidence")
    check = run.context["evidence_unresolved"]["checks"][0]
    assert check["type"] == "evidence_families" and "metrics: unavailable (prometheus_http_500)" in check["detail"]
    assert not dict(run.loop_counters or {})  # no loop step consumed
    assert "An evidence source the alert's target needs could not answer" in run.node_state["pause"]["message"]


@pytest.mark.asyncio
async def test_a_phase_turn_with_metrics_for_the_target_completes(db):
    from tests.test_workflow_run_tdd_evidence import phase_turn_with_history

    run, session, resolution = await _phased_run(db, _check(required=["metrics"]))
    await phase_turn_with_history(db, session.id, resolution, [_history(OK)])
    await db.refresh(run)
    assert run.status == "completed" and run.pause_reason is None, (run.status, run.pause_reason)


@pytest.mark.asyncio
async def test_the_tool_scope_is_read_from_the_sessions_run_never_from_params(monkeypatch):
    from app.services.workflow_runs import records
    from app.tools.alert_scope import run_alert_scope
    from app.tools.context import ToolContext

    run = SimpleNamespace(context={})
    target = {"id": "checkout", "kubernetes": {"namespace": "shop", "connection_id": "k8s-prod"},
              "logs": {"selector": '{namespace="shop"}'}, "metrics": {"selector": '{service="checkout"}'},
              "ci": {"jenkins_jobs": ["deploy-checkout", ""]}}
    start = datetime(2026, 10, 15, 9, 30, tzinfo=UTC)
    sessions: list[str] = []

    async def active_run_for_session(_db, session_id):
        sessions.append(session_id)
        return run if session_id == "bound" else None

    monkeypatch.setattr(records, "active_run_for_session", active_run_for_session)
    monkeypatch.setattr(families, "_alert_readers", lambda: (lambda _run: target, lambda _run: (start, None)))
    context = ToolContext(user_id="u", project_ids=["p"], roles=[], session_id="bound", project_config={},
                          db=object())
    scope = await run_alert_scope(context)
    assert (scope.target_id, scope.namespace, scope.connection_id, scope.logs_selector, scope.metrics_selector,
            scope.jenkins_jobs, scope.window_start, scope.window_end) == (
        "checkout", "shop", "k8s-prod", '{namespace="shop"}', '{service="checkout"}', ("deploy-checkout",), start,
        None)
    context.session_id = "chat"
    assert await run_alert_scope(context) is None and sessions == ["bound", "chat"]
    context.db = None
    assert await run_alert_scope(context) is None


def test_without_a_mapped_target_the_opt_in_fallback_counts_answered_calls():
    # D2 a: the target mapping is opt-in per Action, so E also runs for unmapped alerts and manual starts.
    check = _check(from_target=True, without_target={"min_count": 2})
    assert validate_checks([check]) == []
    for fallback in ({"min_count": 0}, {"min_count": "2"}, {"min": 2}, 2):
        assert validate_checks([_check(from_target=True, without_target=fallback)]), fallback
    answered = [_use("query_prometheus", {}), _use("get_pod_logs", {"logs": "boom"})]
    passed = evaluate_check(check, TurnEvidence(tools=answered))
    assert (passed.outcome, passed.unresolved) == (PASSED, False)
    assert passed.detail == "no mapped alert target: 2 of 2 answered evidence calls"
    failed = evaluate_check(check, TurnEvidence(tools=[answered[0], _use("query_loki", {"error": "loki_http_500"})]))
    assert (failed.outcome, failed.unresolved) == (FAILED, False)
    # With a mapped target the fallback plays no part: the target's families decide.
    scoped = TurnEvidence(tools=answered, alert_scope={**SCOPE, "required_families": ["metrics"]})
    assert evaluate_check(check, scoped).outcome == FAILED
