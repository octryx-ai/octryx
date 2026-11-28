"""Incident analysis (E) starts from a signed test alert and hands its hypothesis over to a bug fix run."""

from __future__ import annotations

import pytest

from app.models import Session, TaskRun, WorkflowRun
from app.runtime_lifecycle import get_task_scheduler
from app.services.admin.connector import admin_webhook_service
from app.services.workflow_runs.actions import perform_action
from app.services.workflow_runs.records import active_run_for_session
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.test_inbound_alert_starts_action import _setup
from tests.test_workflow_run_platform_actions import FakeTools
from tests.workflow_acceptance_b_e_support import _server_pipeline  # noqa: F401
from tests.workflow_acceptance_support import (  # noqa: F401 - the stubbed Jira and GitHub fixture
    _phase_turn,
    submitted,
)

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.mark.asyncio
async def test_incident_analysis_starts_from_a_signed_test_alert_and_hands_over_to_bug_fix(client, db, monkeypatch):

    admin, _project, task, created = await _setup(db)
    task.config = {**task.config, "workflow_run": {"workflow_key": "incident-analysis",
                                                   "repository": "github:acme/pay", "jira_project_key": "OPS"}}
    await db.commit()
    tools = FakeTools(monkeypatch, {"create_jira_ticket": [{"ticket_id": "OPS-12", "status": "created"}]})

    accepted = await admin_webhook_service.send_test_alert(db, webhook_id=created["id"], viewer_id=admin.id, sample="firing_error_rate")
    assert accepted["signature"] == "hmac_timestamped"  # the real signature check
    await get_task_scheduler()._execute_task(task.id, task_run_id=accepted["task_run_id"], trigger_type="webhook",
                                             trigger_id=created["id"])
    task_run = await db.get(TaskRun, accepted["task_run_id"])
    run = await active_run_for_session(db, task_run.session_id)
    assert run is not None and run.workflow_key == "incident-analysis" and run.requested_by == admin.id
    assert run.context["alert"]["test"] is True and run.context["alert"]["title"]  # the alert as data
    session = await db.get(Session, task_run.session_id)
    assert session.user_id != admin.id  # the analysis runs as the webhook's automation identity

    evidence = [{"tool_name": name, "status": "success", "result": {}} for name in ("query_prometheus", "get_pod_logs")]
    await _phase_turn(db, session.id, evidence)
    hypothesis = {"summary": "Error rate after the deploy", "cause": "The new release exhausts the pool.",
                  "impact": "5% of checkouts fail.", "next_step": "Fix the connection leak.", "code_fix_needed": True,
                  "sources": ["https://kb.example.com/runbooks/pool"]}
    await _phase_turn(db, session.id, [{"tool_name": "knowledge_search", "status": "success", "result": {}},
                                       await submitted(db, session.id, "submit_incident_hypothesis", hypothesis)])
    run = await db.get(WorkflowRun, run.id)
    assert run.current_node_id == "confirm_fix"
    shown = run.node_state["waiting"]["payload"]
    assert (shown["shows"], shown["output"]["cause"]) == ("incident_hypothesis", hypothesis["cause"])
    # The card and the confirmation say the run came from a test alert, so nobody opens a Bug for no incident.
    from app.services.workflow_runs.views import run_view

    assert run.node_state["waiting"]["payload"]["test_alert"] is True
    assert (await run_view(db, run, access="write"))["test_alert"] is True
    await perform_action(db, run, user=admin, body={"action": "confirm",
                                                    "payload_hash": run.node_state["waiting"]["payload_hash"]})
    create = next(call for call in tools.calls if call[0] == "create_jira_ticket")
    assert (create[1]["project_key"], create[1]["issue_type"]) == ("OPS", "Bug")
    assert create[1]["summary"] == hypothesis["summary"] and "Cause: The new release" in create[1]["description"]
    assert (run.status, run.waiting_kind, run.ticket_key) == ("waiting", "sub_workflow", "OPS-12")
    child = await db.get(WorkflowRun, run.node_state["child_run_id"])
    assert (child.workflow_key, child.ticket_key, child.repository) == ("bug-fix-reproduction", "OPS-12",
                                                                       "github:acme/pay")
    assert [call[0] for call in tools.calls].count("create_jira_ticket") == 1  # C reuses the bug ticket
    assert child.context["handoff"]["incident_hypothesis"]["cause"] == hypothesis["cause"]  # C's phases read it
