"""Workflow E (``incident-analysis``) reads the alert and judges evidence families.

Contract: the evidence phase and its gate judge ``evidence_families`` for the mapped target and window, and both
evidence-reading phases offer ``get_run_alert`` and the ServiceNow reads. End to end on the
seeded E: a phase turn whose only metrics source is unavailable pauses ``evidence_unresolved`` (no loop step); a
targeted ``ok`` passes the evidence phase and its gate on the recorded family records.
"""

from __future__ import annotations

import copy

import pytest

from app.services.workflow_checks.evidence_families import OK, UNAVAILABLE, evidence_envelope, with_envelope
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.seeding import phased_seeds
from app.tools.definitions import get_tool_definition_metadata

KEY = "incident-analysis"
# The alert and ServiceNow reads both evidence-reading phases offer (list_jenkins_builds is service-only and hidden).
OFFERED = ("get_run_alert", "list_servicenow_incidents", "get_servicenow_record", "list_servicenow_changes")
FAMILIES_CHECK = {"type": "evidence_families", "params": {"from_target": True, "without_target": {"min_count": 2}},
                  "blocking": True}
WINDOW = {"start": "2026-10-15T09:30:00Z", "end": None}
IN_WINDOW = {"start": "2026-10-15T09:30:00Z", "end": "2026-10-15T10:05:00Z"}
TARGET = {"id": "checkout", "required_families": ["metrics"], "kubernetes": {"namespace": "shop"}}


def _seed() -> dict:
    return next(seed for seed in phased_seeds() if seed["key"] == KEY)


def _nodes(definition: dict) -> dict[str, dict]:
    return {node["id"]: node for node in definition["nodes"]}


def test_the_evidence_phase_and_its_gate_judge_families_and_offer_the_alert_and_ticket_reads():
    definition = _seed()["definition"]
    nodes = _nodes(definition)
    evidence = nodes["evidence"]["config"]
    assert [{key: check[key] for key in ("type", "params", "blocking")}
            for check in evidence["workflow_contract"]["checks"]] == [FAMILIES_CHECK]
    assert [{key: check[key] for key in ("type", "params", "blocking")}
            for check in nodes["evidence_gate"]["config"]["checks"]] == [FAMILIES_CHECK]
    assert "get_run_alert" in evidence["workflow_contract"]["when_to_use"]
    for node_id in ("evidence", "hypothesis"):
        allowlist = nodes[node_id]["config"]["tool_policy"]["allowlist"]
        assert set(OFFERED) <= set(allowlist), node_id
        assert "list_jenkins_builds" not in allowlist, node_id
        assert len(allowlist) == len(set(allowlist)), node_id
    assert nodes["hypothesis"]["config"]["tool_policy"]["allowlist"][-1] == "submit_incident_hypothesis"
    assert definition["nodes"][1]["id"] == "evidence", "the Action turn stays the first phase"
    assert validate_phased_definition(definition)["errors"] == []


def test_the_new_tools_are_read_only_so_the_read_only_workflow_may_offer_them():
    for name in ("get_run_alert", "list_jenkins_builds"):
        metadata = get_tool_definition_metadata(name)
        assert (metadata.risk, metadata.mutates_state) == ("read", False), name
    assert get_tool_definition_metadata("list_jenkins_builds").connector == "jenkins"
    assert get_tool_definition_metadata("get_run_alert").connector is None


# --- the seeded E end to end ----------------------------------------------------------------------------------------


def _metrics(status: str, reason: str = "") -> dict:
    envelope = evidence_envelope("metrics", status, target_id="checkout", namespace="shop", window=IN_WINDOW,
                                 count=1 if status == OK else 0, reason=reason)
    result = with_envelope({"error": reason} if reason else {"range_result": {"result": [{}]}}, envelope)
    return {"tool_name": "query_prometheus", "status": "success", "result": result}


async def _alert_run(db):
    from app.services.workflow_runs.binding import run_turn_resolution
    from app.services.workflow_runs.records import new_chat_session, start_run
    from tests.phased_workflow_fixtures import admin_user, run_workspace

    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=KEY, project_id=workspace_id, session=session)
    assert run.current_node_id == "evidence"
    run.context = {**dict(run.context or {}), "alert_target": copy.deepcopy(TARGET),
                   "alert": {"v": 1, "title": "Checkout errors", "window": WINDOW}}
    await db.commit()
    resolution = await run_turn_resolution(db, session, user_message="Collect the evidence.")
    return run, session, resolution


@pytest.mark.asyncio
async def test_on_the_seeded_e_an_unavailable_metrics_source_pauses_evidence_unresolved_without_a_loop(db):
    from tests.test_workflow_run_tdd_evidence import phase_turn_with_history

    run, session, resolution = await _alert_run(db)
    await phase_turn_with_history(db, session.id, resolution, [_metrics(UNAVAILABLE, "prometheus_http_500")])
    await db.refresh(run)
    assert (run.status, run.pause_reason, run.current_node_id) == ("paused", "evidence_unresolved", "evidence")
    [check] = run.context["evidence_unresolved"]["checks"]
    assert check["type"] == "evidence_families" and "metrics: unavailable (prometheus_http_500)" in check["detail"]
    assert all(counter["used"] == 0 for counter in dict(run.loop_counters or {}).values()), run.loop_counters
    assert "An evidence source the alert's target needs could not answer" in run.node_state["pause"]["message"]


@pytest.mark.asyncio
async def test_on_the_seeded_e_targeted_metrics_pass_the_phase_and_its_gate_on_the_recorded_families(db):
    from tests.test_workflow_run_tdd_evidence import phase_turn_with_history

    run, session, resolution = await _alert_run(db)
    await phase_turn_with_history(db, session.id, resolution, [_metrics(OK)])
    await db.refresh(run)
    assert run.status == "running" and run.current_node_id == "hypothesis", (run.status, run.current_node_id)
    [record] = run.context["evidence"]["evidence"]["evidence_records"]
    assert (record["family"], record["status"], record["target_id"]) == ("metrics", "ok", "checkout")
    gate = dict(run.gate_results or {}).get("evidence_gate") or {}
    assert gate, run.gate_results
