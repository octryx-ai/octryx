"""A triage whose follow-up workflow did not start is visible, not silent.

With only a model key and no device, a bug's triage runs on the server and its follow-up (a fix that builds and
tests) is refused with ``server_build_not_allowed``. The refusal is recorded on the triage run, and the run card
(``routing``) and a work item's runs (``follow_up_failed``) carry it, and the message says how to get a device.
"""

from __future__ import annotations

import uuid

import pytest

from app.models import Project, WorkflowRun
from app.models.runtime.secure_work import WorkItem
from app.services.workflow_runs.run_notices import follow_up_failed
from app.services.workflow_runs.runtime_target.server_build import workflow_message

REFUSAL = {"state": "failed", "type": "bug", "workflow_key": "bug-fix-reproduction", "code": "server_build_not_allowed",
           "message": workflow_message(["tests_green"]), "at": "2026-11-21T03:00:00"}


def test_the_server_build_refusal_says_how_to_get_a_device():
    message = workflow_message(["tests_green"])
    assert "Run it on your Mac (choose your device as the run location)" in message
    assert "pair Claude Code with the launcher (Agents › Install octryx-claude)" in message


def test_only_a_failed_follow_up_is_reported():
    run = WorkflowRun(context={"routing": REFUSAL})
    assert follow_up_failed(run) == {"workflow_key": "bug-fix-reproduction", "code": "server_build_not_allowed",
                                     "message": REFUSAL["message"]}
    assert follow_up_failed(WorkflowRun(context={"routing": {"state": "routed", "run_id": "r"}})) is None
    assert follow_up_failed(WorkflowRun(context={})) is None


@pytest.mark.asyncio
async def test_a_work_items_runs_and_the_run_card_show_the_refused_follow_up(client, auth_headers, db, auth_user):
    project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:6]}", is_active=True)
    db.add(project)
    await db.flush()
    item = WorkItem(id=str(uuid.uuid4()), project_id=project.id, source_key="OCX-1", source_instance=project.name,
                    title="Discount bug")
    db.add(item)
    await db.flush()
    triage = WorkflowRun(id=str(uuid.uuid4()), project_id=project.id, workflow_kind="phased",
                         workflow_key="jira-intake-triage", title="OCX-1 triage", work_item_id=item.id,
                         status="completed", requested_by=auth_user.id, context={"routing": REFUSAL})
    db.add(triage)
    await db.commit()

    rows = (await client.get(f"/api/v1/workflow-runs?work_item_id={item.id}", headers=auth_headers)).json()["runs"]
    row = next(row for row in rows if row["id"] == triage.id)
    assert row["follow_up_failed"]["code"] == "server_build_not_allowed"
    assert "Install octryx-claude" in row["follow_up_failed"]["message"]
    card = (await client.get(f"/api/v1/workflow-runs/{triage.id}", headers=auth_headers)).json()["run"]
    assert card["routing"]["state"] == "failed" and card["routing"]["workflow_key"] == "bug-fix-reproduction"
