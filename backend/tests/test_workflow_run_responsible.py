"""The responsible person of a workflow run and taking a run over.

Contract: a person's start keeps the requester responsible; an automatic start for a Work item walks the chain
reporter → assignee over active human Workspace members (else nobody: the existing audience applies). The responsible
person gets the run's confirmations (offered, decidable, in the attention queue) in addition to today's rights; the
run never decides on its own. ``take_over`` needs write access to the run (requester, Work item owner, admin), is
audited and is refused on an ended run or for a reader. A platform admin outside the Workspace who started the run
takes it over themselves (self-take-over: ``requester`` → ``taken_over``, audited) and only then decides; anyone else
already responsible is refused. Detail and list show ``responsible``.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog, User, UserProject, WorkflowRunEvent
from app.models.runtime.secure_work import WorkItem
from app.services.attention.service import attention
from app.services.secure_work.servicenow.records import _caller
from app.services.workflow_runs.actions import available_actions
from app.services.workflow_runs.attention import inbox_items
from app.services.workflow_runs.hitl_actions import decision_actions
from app.services.workflow_runs.records import new_chat_session, start_run
from app.services.workflow_runs.responsible import RESPONSIBLE_CHAIN, responsible_for
from app.services.workflow_runs.states import STATUS_WAITING, WAITING_TOOL_APPROVAL
from tests.knowledge_evidence_seed_support import seed_member, seed_outsider, seed_workspace
from tests.phased_workflow_fixtures import admin_user, publish_phased
from tests.policy_engine_support import bearer

pytestmark = pytest.mark.asyncio

DEFINITION = {
    "execution_kind": "phased",
    "nodes": [{"id": "start", "type": "start"},
              {"id": "go", "type": "user_confirmation", "label": "Go on?", "config": {"subject": "advance"}},
              {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
              {"id": "blocked", "type": "outcome", "config": {"outcome": "blocked"}}],
    "edges": [{"id": "e0", "source_node_id": "start", "target_node_id": "go"},
              {"id": "r0", "source_node_id": "go", "target_node_id": "done", "when": "confirmed"},
              {"id": "r1", "source_node_id": "go", "target_node_id": "blocked", "when": "changed"},
              {"id": "r2", "source_node_id": "go", "target_node_id": "blocked", "when": "stopped"}],
}


async def _person(db, workspace_id: str | None) -> User:
    user_id = await seed_member(db, workspace_id=workspace_id, role="member") if workspace_id else await seed_outsider(db)
    return await db.get(User, user_id)


async def _item(db, workspace_id: str, *, reporter: str | None = None, assignee: str | None = None) -> WorkItem:
    item = WorkItem(project_id=workspace_id, source_type="jira", source_instance="test",
                    source_key=f"RP-{uuid.uuid4().hex[:6]}", title="Checkout fails", reporter=reporter,
                    assignee=assignee)
    db.add(item)
    await db.flush()
    return item


async def _case(db, *, automatic: bool = False):
    """A Workspace with a requester, the item's reporter and assignee (its owner) and a plain member; the run waits
    at a legacy confirmation (no authored decider)."""
    workspace_id = await seed_workspace(db)
    requester, reporter, owner, viewer = [await _person(db, workspace_id) for _ in range(4)]
    item = await _item(db, workspace_id, reporter=reporter.username, assignee=owner.email)
    key = await publish_phased(db, DEFINITION)
    run = await start_run(db, user=requester, workflow_key=key, project_id=workspace_id, work_item_id=item.id,
                          session=await new_chat_session(db, requester, workspace_id), automatic=automatic)
    await db.commit()
    assert (run.status, run.current_node_id) == (STATUS_WAITING, "go")
    return run, requester, reporter, owner, viewer, item


def _confirm(run) -> dict:
    return {"action": "confirm", "payload_hash": run.node_state["waiting"]["payload_hash"]}


# --- the chain ---------------------------------------------------------------------------------------------------


async def test_the_chain_is_reporter_then_assignee_then_nobody(db):
    workspace_id = await seed_workspace(db)
    reporter, assignee = await _person(db, workspace_id), await _person(db, workspace_id)
    assert RESPONSIBLE_CHAIN == ("reporter", "assignee")
    item = await _item(db, workspace_id, reporter=reporter.email.upper(), assignee=assignee.username)
    assert await responsible_for(db, item, workspace_id) == (reporter.id, "reporter")
    item.reporter = "someone-else@example.com"
    assert await responsible_for(db, item, workspace_id) == (assignee.id, "assignee")
    item.assignee = None
    assert await responsible_for(db, item, workspace_id) is None  # broadcast: the existing audience applies
    assert await responsible_for(db, None, workspace_id) is None


async def test_inactive_people_and_people_without_a_workspace_role_are_skipped(db):
    workspace_id = await seed_workspace(db)
    reporter, assignee = await _person(db, workspace_id), await _person(db, workspace_id)
    stranger = await _person(db, None)
    item = await _item(db, workspace_id, reporter=reporter.username, assignee=assignee.username)
    reporter.is_active = False
    await db.flush()
    assert await responsible_for(db, item, workspace_id) == (assignee.id, "assignee")
    item.reporter = stranger.username  # an active platform account, but no role in this Workspace
    assert await responsible_for(db, item, workspace_id) == (assignee.id, "assignee")
    assignee.account_type = "service"
    await db.flush()
    assert await responsible_for(db, item, workspace_id) is None


async def test_a_servicenow_caller_is_stored_as_the_reporter_identifier():
    assert _caller({"caller_id": "Jane Doe", "caller_id.email": "jane@example.com"}) == "jane@example.com"
    assert _caller({"caller_id": {"value": "6816f79c", "display_value": "Jane Doe"}}) == "6816f79c"
    assert _caller({}) is None


# --- the start paths ---------------------------------------------------------------------------------------------


async def test_a_person_started_run_keeps_its_requester_responsible(db):
    run, requester, _reporter, _owner, _viewer, _item_row = await _case(db)
    assert (run.responsible_user_id, run.responsible_source) == (requester.id, "requester")


async def test_an_automatic_start_makes_the_reporter_responsible_and_gives_them_the_confirmation(client, db):
    run, requester, reporter, _owner, viewer, _item_row = await _case(db, automatic=True)
    assert (run.requested_by, run.responsible_user_id, run.responsible_source) == (
        requester.id, reporter.id, "reporter")
    # The reporter reads the run (Workspace member) and is offered exactly the confirmation; a plain member is not.
    assert {item["key"] for item in await available_actions(db, run, access="read", user=reporter)} == {
        "confirm", "change", "stop"}
    assert await available_actions(db, run, access="read", user=viewer) == []
    queue = await attention(db, reporter)
    [entry] = [item for item in queue["items"] if item.get("id") == run.id]
    assert entry["kind"] == "gate" and {action["key"] for action in entry["actions"]} == {"confirm", "change", "stop"}
    assert not [item for item in (await attention(db, viewer))["items"] if item.get("id") == run.id]
    assert [item["id"] for item in await inbox_items(db, reporter.id) if item["kind"] == "workflow_run_confirmation"
            ] == [run.id]
    refused = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", json=_confirm(run),
                                headers=bearer(viewer.id))
    assert refused.status_code == 403 and run.status == STATUS_WAITING
    decided = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", json=_confirm(run),
                                headers=bearer(reporter.id))
    assert decided.status_code == 200, decided.text
    assert decided.json()["run"]["status"] == "completed"


async def test_without_an_answer_the_run_keeps_waiting(db):
    run, *_rest = await _case(db, automatic=True)
    from app.services.workflow_runs.sweep import sweep_waiting_runs

    await sweep_waiting_runs(db)
    await db.refresh(run)
    assert (run.status, run.current_node_id, run.outcome) == (STATUS_WAITING, "go", None)


# --- take over ---------------------------------------------------------------------------------------------------


async def test_the_work_item_owner_takes_the_run_over_audited_and_gets_its_approvals(client, db):
    run, requester, _reporter, owner, viewer, _item_row = await _case(db)
    path = f"/api/v1/workflow-runs/{run.id}"
    assert "take_over" in {item["key"] for item in await available_actions(db, run, access="write", user=owner)}

    taken = await client.post(f"{path}/actions", json={"action": "take_over"}, headers=bearer(owner.id))
    assert taken.status_code == 200, taken.text
    view = taken.json()["run"]
    assert view["responsible"] == {"user_id": owner.id, "display_name": owner.display_name or owner.username,
                                   "source": "taken_over"}
    assert "take_over" not in {item["key"] for item in view["actions"]}  # already responsible
    assert "confirm" in {item["key"] for item in view["actions"]}
    await db.refresh(run)
    assert (run.requested_by, run.status) == (requester.id, STATUS_WAITING)  # the requester keeps everything else
    [audit] = (await db.execute(select(AuditLog).where(AuditLog.action == "workflow_run.taken_over",
                                                       AuditLog.resource_id == run.id))).scalars()
    assert audit.user_id == owner.id and audit.details == {
        "run_id": run.id, "previous_responsible_user_id": requester.id, "previous_source": "requester",
        "responsible_user_id": owner.id}
    assert (await db.execute(select(WorkflowRunEvent.detail).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == "responsible_taken_over"))).scalar_one()[
        "to"] == owner.id

    # From now on the confirmation is in the new responsible person's queue; the requester still decides too.
    [entry] = [item for item in (await attention(db, owner))["items"] if item.get("id") == run.id]
    assert {action["key"] for action in entry["actions"]} == {"confirm", "change", "stop"}
    assert {item["key"] for item in await decision_actions(db, run, user=requester)} == {"confirm", "change", "stop"}
    assert not [item for item in (await attention(db, viewer))["items"] if item.get("id") == run.id]

    again = await client.post(f"{path}/actions", json={"action": "take_over"}, headers=bearer(owner.id))
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_responsible"
    listed = (await client.get("/api/v1/workflow-runs", params={"work_item_id": run.work_item_id},
                               headers=bearer(owner.id))).json()["runs"]
    assert [row["responsible"]["user_id"] for row in listed] == [owner.id]
    detail = (await client.get(path, headers=bearer(viewer.id))).json()["run"]
    assert detail["responsible"]["source"] == "taken_over"


async def test_a_reader_cannot_take_over_and_an_ended_run_is_refused(client, db, auth_headers):
    run, requester, _reporter, _owner, viewer, _item_row = await _case(db)
    path = f"/api/v1/workflow-runs/{run.id}/actions"
    refused = await client.post(path, json={"action": "take_over"}, headers=bearer(viewer.id))
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "take_over_not_permitted"
    await db.refresh(run)
    assert run.responsible_user_id == requester.id

    admin = await admin_user(db)
    taken = await client.post(path, json={"action": "take_over"}, headers=auth_headers)  # a platform admin may
    assert taken.status_code == 200 and taken.json()["run"]["responsible"]["user_id"] == admin.id

    decided = await client.post(path, json=_confirm(run), headers=bearer(requester.id))
    assert decided.status_code == 200 and decided.json()["run"]["status"] == "completed"
    ended = await client.post(path, json={"action": "take_over"}, headers=bearer(requester.id))
    assert ended.status_code == 409 and ended.json()["detail"]["code"] == "run_finished"


async def test_the_responsible_person_allows_a_runs_tool_step(db):
    run, requester, reporter, _owner, viewer, _item_row = await _case(db, automatic=True)
    run.waiting_kind = WAITING_TOOL_APPROVAL
    run.node_state = {**dict(run.node_state), "waiting": {"kind": WAITING_TOOL_APPROVAL, "approval_id": "a1",
                                                           "action": "jira.comment"}}
    await db.flush()
    for person in (requester, reporter):
        assert {item["key"] for item in await decision_actions(db, run, user=person)} == {"approve_tool",
                                                                                         "reject_tool"}
    assert await decision_actions(db, run, user=viewer) == []


async def test_a_responsible_person_who_left_the_workspace_decides_nothing(db):
    run, _requester, reporter, _owner, _viewer, _item_row = await _case(db, automatic=True)
    membership = await db.get(UserProject, (reporter.id, run.project_id))
    await db.delete(membership)
    await db.flush()
    assert await decision_actions(db, run, user=reporter) == []


# --- a platform admin outside the Workspace ----------------------------------------------------------------------


async def _decider_ids(db, run) -> tuple[str, ...]:
    from app.services.workflow_runs.decider import resolve_decider
    from app.services.workflow_runs.graph import graph_for_run

    node = (await graph_for_run(db, run)).nodes[str(run.current_node_id)]
    return (await resolve_decider(db, run, node)).user_ids


async def test_a_non_member_admin_who_starts_a_run_is_no_default_decider(client, db, auth_headers):
    """A platform admin may start a run in any Workspace (cross-Workspace Work scope), and is its responsible
    person by that start, but becomes a decider only by an explicit takeover, never by starting it."""
    workspace_id = await seed_workspace(db)
    admin = await admin_user(db)
    assert await db.get(UserProject, (admin.id, workspace_id)) is None
    key = await publish_phased(db, DEFINITION)
    run = await start_run(db, user=admin, workflow_key=key, project_id=workspace_id,
                          session=await new_chat_session(db, admin, workspace_id))
    await db.commit()
    assert (run.status, run.current_node_id) == (STATUS_WAITING, "go")
    assert (run.responsible_user_id, run.responsible_source) == (admin.id, "requester")
    assert admin.id not in await _decider_ids(db, run)
    refused = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", json=_confirm(run), headers=auth_headers)
    assert refused.status_code in (403, 409)
    assert refused.json()["detail"]["code"] in ("decider_unresolved", "not_decider")
    await db.refresh(run)
    assert run.status == STATUS_WAITING


async def test_a_member_requester_decides_and_an_admins_explicit_takeover_makes_the_admin_a_decider(
        client, db, auth_headers):
    run, requester, _reporter, _owner, _viewer, _item_row = await _case(db)
    admin = await admin_user(db)
    assert await db.get(UserProject, (admin.id, run.project_id)) is None
    assert await _decider_ids(db, run) == (requester.id,)

    path = f"/api/v1/workflow-runs/{run.id}/actions"
    taken = await client.post(path, json={"action": "take_over"}, headers=auth_headers)
    assert taken.status_code == 200 and taken.json()["run"]["responsible"]["source"] == "taken_over"
    await db.refresh(run)
    assert set(await _decider_ids(db, run)) == {requester.id, admin.id}
    decided = await client.post(path, json=_confirm(run), headers=auth_headers)
    assert decided.status_code == 200 and decided.json()["run"]["status"] == "completed"


async def test_a_non_member_admin_who_started_the_run_takes_it_over_audited_and_then_decides(client, db, auth_headers):
    workspace_id = await seed_workspace(db)
    admin = await admin_user(db)
    key = await publish_phased(db, DEFINITION)
    run = await start_run(db, user=admin, workflow_key=key, project_id=workspace_id,
                          session=await new_chat_session(db, admin, workspace_id))
    await db.commit()
    offered = {item["key"]: item for item in await available_actions(db, run, access="write", user=admin)}
    assert offered["take_over"]["label"] == "Take over (decide this run yourself)"
    assert "confirm" not in offered

    path = f"/api/v1/workflow-runs/{run.id}/actions"
    taken = await client.post(path, json={"action": "take_over"}, headers=auth_headers)
    assert taken.status_code == 200, taken.text
    assert taken.json()["run"]["responsible"]["source"] == "taken_over"
    assert "take_over" not in {item["key"] for item in taken.json()["run"]["actions"]}
    await db.refresh(run)
    assert (run.responsible_user_id, run.responsible_source, run.requested_by) == (admin.id, "taken_over", admin.id)
    [audit] = (await db.execute(select(AuditLog).where(AuditLog.action == "workflow_run.taken_over",
                                                       AuditLog.resource_id == run.id))).scalars()
    assert audit.user_id == admin.id and audit.details == {
        "run_id": run.id, "previous_responsible_user_id": admin.id, "previous_source": "requester",
        "responsible_user_id": admin.id}
    assert (await db.execute(select(WorkflowRunEvent.detail).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == "responsible_taken_over"))).scalar_one()[
        "from_source"] == "requester"
    assert await _decider_ids(db, run) == (admin.id,)
    again = await client.post(path, json={"action": "take_over"}, headers=auth_headers)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_responsible"
    decided = await client.post(path, json=_confirm(run), headers=auth_headers)
    assert decided.status_code == 200 and decided.json()["run"]["status"] == "completed"


async def test_a_non_admin_outside_the_workspace_neither_takes_over_nor_decides(client, db):
    run, requester, _reporter, _owner, _viewer, _item_row = await _case(db)
    outsider = await _person(db, None)
    path = f"/api/v1/workflow-runs/{run.id}/actions"
    refused = await client.post(path, json={"action": "take_over"}, headers=bearer(outsider.id))
    assert refused.status_code in (403, 404)
    assert refused.json()["detail"]["code"] in ("take_over_not_permitted", "unknown_run")

    # The requester who left the Workspace stays responsible by their start, but no self-take-over makes them a
    # decider.
    await db.delete(await db.get(UserProject, (requester.id, run.project_id)))
    await db.commit()
    assert "take_over" not in {item["key"] for item in await available_actions(db, run, access="write",
                                                                               user=requester)}
    self_taken = await client.post(path, json={"action": "take_over"}, headers=bearer(requester.id))
    assert self_taken.status_code == 409 and self_taken.json()["detail"]["code"] == "already_responsible"
    await db.refresh(run)
    assert (run.responsible_user_id, run.responsible_source) == (requester.id, "requester")
    assert requester.id not in await _decider_ids(db, run)
    decided = await client.post(path, json=_confirm(run), headers=bearer(requester.id))
    assert decided.status_code in (403, 409) and decided.json()["detail"]["code"] in ("decider_unresolved",
                                                                                     "not_decider")


async def test_a_member_requester_is_already_responsible_and_never_offered_a_self_take_over(client, db):
    run, requester, *_rest = await _case(db)
    assert "take_over" not in {item["key"] for item in await available_actions(db, run, access="write",
                                                                               user=requester)}
    again = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", json={"action": "take_over"},
                              headers=bearer(requester.id))
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_responsible"
    await db.refresh(run)
    assert (run.responsible_user_id, run.responsible_source) == (requester.id, "requester")
    assert await _decider_ids(db, run) == (requester.id,)
