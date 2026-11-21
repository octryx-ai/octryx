"""Routing by type after the triage.

Contract: a triage run that completes ``done`` starts exactly one follow-up run of the workflow its Definition of
Ready's ``type`` maps to (defaults feature → epic-delivery, bug → bug-fix-reproduction, incident →
incident-analysis; the Workspace setting overrides them, a ``routing`` block on the triage definition's outcome
overrides that). The follow-up carries the Work item, the repository, the requester, the responsible person (copied,
never resolved again) and the Definition of Ready (``context.handoff``); it runs where the triage ran when that is
still the requester's own target, else on the Server. An unknown or switched-off type starts nothing and records
"No route for type X". ``routed_to`` / ``routed_from`` events link both runs; finishing again never starts a second
one. ``entry_workflow_for``: a Jira Incident and a ServiceNow ``incident`` skip the triage.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.models import Project, Role, User, UserRole, WorkflowRun, WorkflowRunEvent
from app.models.security.device import UserDevice
from app.services.workflow_runs.actions import perform_action
from app.services.workflow_runs.phase_outputs import available_inputs, submit_output
from app.services.workflow_runs.records import main_session_id, new_chat_session, start_run
from app.services.workflow_runs.triage_routing import ROUTING_KEY, route_after_triage
from tests.knowledge_evidence_seed_support import seed_outsider, seed_workspace
from tests.phased_workflow_fixtures import admin_user, publish_phased, run_workspace
from tests.test_workflow_run_pause import _turn
from tests.test_workflow_run_platform_actions import FakeTools
from tests.triage_routing_support import _item, _server_pipeline, _triage_seed  # noqa: F401

FEATURE = {"type": "feature", "summary": "Round totals", "acceptance_criteria": ["Totals round half up"],
           "repository": "github:acme/pay"}


BUG = {"type": "bug", "summary": "Totals wrong", "reproduction_steps": ["Add 0.005"], "expected": "0.01",
       "actual": "0.00", "repository": "github:acme/pay"}


async def _at_ready(db, monkeypatch, record: dict, *, project_id: str | None = None,
                    workflow_key: str = "jira-intake-triage", context: dict | None = None):
    """A triage run waiting at its "Start delivery?" confirmation with ``record`` as its Definition of Ready."""
    FakeTools(monkeypatch, {"get_jira_ticket": [{"key": "PAY-1"}]})
    admin = await admin_user(db)
    item = await _item(db, project_id=project_id)
    project_id = await run_workspace(db, admin, item.id)
    run = await start_run(db, user=admin, workflow_key=workflow_key, project_id=project_id, work_item_id=item.id,
                          session=await new_chat_session(db, admin, project_id))
    if context:
        run.context = {**dict(run.context or {}), **context}
    await submit_output(db, run, "submit_definition_of_ready", record)
    await _turn(db, await main_session_id(db, run), ["submit_definition_of_ready"])
    return run, item, admin


async def _confirm(db, run, admin) -> None:
    waiting = run.node_state["waiting"]
    await perform_action(db, run, user=admin, body={"action": "confirm", "payload_hash": waiting["payload_hash"]})


async def _follow_ups(db, triage: WorkflowRun) -> list[WorkflowRun]:
    return list((await db.execute(select(WorkflowRun).where(
        WorkflowRun.work_item_id == triage.work_item_id, WorkflowRun.id != triage.id))).scalars())


async def _events(db, run: WorkflowRun, kind: str) -> list[WorkflowRunEvent]:
    return list((await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == kind))).scalars())


# ---- after the triage ---------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_ready_feature_starts_one_feature_delivery_run_carrying_item_requester_responsible_and_dor(
        db, monkeypatch):
    run, item, admin = await _at_ready(db, monkeypatch, FEATURE, context={"jira_project_key": "PAY"})
    other = await db.get(User, await seed_outsider(db))
    # A platform admin took the run over; the requester of this Workspace-less run is no decider of its own.
    admin_role = (await db.execute(select(Role).where(Role.name == "admin"))).scalar_one()
    db.add(UserRole(user_id=other.id, role_id=admin_role.id))
    run.responsible_user_id, run.responsible_source = other.id, "taken_over"  # copied, never resolved again
    await _confirm(db, run, other)

    assert (run.status, run.outcome) == ("completed", "done")
    [child] = await _follow_ups(db, run)
    assert child.workflow_key == "epic-delivery" and child.parent_run_id is None
    assert (child.work_item_id, child.repository, child.requested_by) == (item.id, "github:acme/pay", admin.id)
    assert (child.responsible_user_id, child.responsible_source) == (other.id, "taken_over")
    context = dict(child.context or {})
    assert context["routed_from"]["run_id"] == run.id and context["routed_from"]["type"] == "feature"
    assert context["jira_project_key"] == "PAY"
    handed = available_inputs(child, [])["definition_of_ready"]
    assert (handed["type"], handed["acceptance_criteria"], handed["complete"]) == (
        "feature", ["Totals round half up"], True)
    assert await main_session_id(db, child) is not None  # its own chat thread

    [routed_to] = await _events(db, run, "routed_to")
    assert routed_to.detail["workflow_key"] == "epic-delivery" and routed_to.detail["run_id"] == child.id
    [routed_from] = await _events(db, child, "routed_from")
    assert routed_from.detail == {"workflow_key": "jira-intake-triage", "run_id": run.id, "type": "feature"}
    assert run.context[ROUTING_KEY]["state"] == "routed" and run.context[ROUTING_KEY]["run_id"] == child.id


@pytest.mark.asyncio
async def test_finishing_again_or_a_lost_marker_never_starts_a_second_follow_up(db, monkeypatch):
    run, _item_, admin = await _at_ready(db, monkeypatch, BUG)
    await _confirm(db, run, admin)
    [child] = await _follow_ups(db, run)
    assert child.workflow_key == "bug-fix-reproduction"

    assert await route_after_triage(db, run, actor_id=admin.id) is None  # a retry / sweep
    context = dict(run.context)
    context.pop(ROUTING_KEY)
    run.context = context  # the marker lost: the follow-up's routed_from still names this triage
    assert await route_after_triage(db, run, actor_id=admin.id) is None
    assert [item.id for item in await _follow_ups(db, run)] == [child.id]
    assert run.context[ROUTING_KEY]["run_id"] == child.id
    assert len(await _events(db, run, "routed_to")) == 1


@pytest.mark.asyncio
async def test_a_type_without_route_starts_nothing_and_says_so(db, monkeypatch):
    run, _item_, admin = await _at_ready(db, monkeypatch, {"type": "task", "summary": "Rename",
                                                           "repository": "github:acme/pay"})
    await _confirm(db, run, admin)
    assert (run.status, run.outcome) == ("completed", "done") and await _follow_ups(db, run) == []
    [event] = await _events(db, run, "routing_no_route")
    assert event.detail["message"] == "No route for type 'task'"
    assert run.context[ROUTING_KEY]["state"] == "no_route"


@pytest.mark.asyncio
async def test_the_workspace_setting_reroutes_or_switches_a_type_off(db, monkeypatch):
    workspace_id = await seed_workspace(db)
    project = await db.get(Project, workspace_id)
    project.config = {"triage_routing": {"routes": {"feature": "incident-analysis", "bug": None}}}
    await db.flush()
    run, _item_, admin = await _at_ready(db, monkeypatch, FEATURE, project_id=workspace_id)
    await _confirm(db, run, admin)
    [child] = await _follow_ups(db, run)
    assert (child.workflow_key, child.project_id) == ("incident-analysis", workspace_id)

    bug, _item_, admin = await _at_ready(db, monkeypatch, BUG, project_id=workspace_id)
    await _confirm(db, bug, admin)
    assert await _follow_ups(db, bug) == []
    [event] = await _events(db, bug, "routing_no_route")
    assert event.detail == {"type": "bug", "message": "No route for type 'bug'", "switched_off": True}


@pytest.mark.asyncio
async def test_a_triage_definition_with_its_own_routing_block_routes_by_it(db, monkeypatch):
    definition = _triage_seed()
    ready = next(node for node in definition["nodes"] if node["id"] == "ready")
    ready["config"][ROUTING_KEY] = {"routes": {"feature": "incident-analysis"}}
    key = await publish_phased(db, definition)
    run, _item_, admin = await _at_ready(db, monkeypatch, FEATURE, workflow_key=key)
    await _confirm(db, run, admin)
    [child] = await _follow_ups(db, run)
    assert child.workflow_key == "incident-analysis"
    assert child.context["routed_from"]["workflow_key"] == key


@pytest.mark.asyncio
async def test_an_incident_type_routes_to_the_incident_analysis(db, monkeypatch):
    run, _item_, admin = await _at_ready(db, monkeypatch, {"type": "incident", "summary": "Checkout down",
                                                           "repository": "github:acme/pay"})
    await _confirm(db, run, admin)
    [child] = await _follow_ups(db, run)
    assert child.workflow_key == "incident-analysis"


@pytest.mark.asyncio
async def test_the_follow_up_never_runs_on_another_persons_device(db, monkeypatch):
    stranger = await db.get(User, await seed_outsider(db))
    device = UserDevice(owner_user_id=stranger.id, name="Their Mac", name_key=f"mac-{uuid.uuid4().hex[:6]}",
                        os="macos", public_key="x", folders=["/work"], profiles=["governed"])
    db.add(device)
    await db.flush()
    foreign = {"kind": "device", "device_id": device.id, "folder": "/work", "profile": "governed"}
    run, _item_, admin = await _at_ready(db, monkeypatch, FEATURE, context={"runtime_target": foreign})
    await _confirm(db, run, admin)
    [child] = await _follow_ups(db, run)
    assert child.context["runtime_target"]["kind"] == "server"
    [routed_to] = await _events(db, run, "routed_to")
    assert routed_to.detail["runtime_target"] == "server"
    assert routed_to.detail["runtime_target_fallback"] == "runtime_device_not_owner"


@pytest.mark.asyncio
async def test_a_triage_on_the_server_hands_the_server_on(db, monkeypatch):
    run, _item_, admin = await _at_ready(db, monkeypatch, FEATURE, context={"runtime_target": {"kind": "server"}})
    await _confirm(db, run, admin)
    [child] = await _follow_ups(db, run)
    assert child.context["runtime_target"]["kind"] == "server"
    [routed_to] = await _events(db, run, "routed_to")
    assert "runtime_target_fallback" not in routed_to.detail


@pytest.mark.asyncio
async def test_a_refused_follow_up_is_recorded_once_and_leaves_the_triage_completed(db, monkeypatch):
    workspace_id = await seed_workspace(db)
    project = await db.get(Project, workspace_id)
    project.config = {"triage_routing": {"routes": {"feature": "not-published-anywhere"}}}
    await db.flush()
    run, _item_, admin = await _at_ready(db, monkeypatch, FEATURE, project_id=workspace_id)
    await _confirm(db, run, admin)
    assert (run.status, run.outcome) == ("completed", "done") and await _follow_ups(db, run) == []
    [event] = await _events(db, run, "routing_failed")
    assert (event.detail["code"], event.detail["workflow_key"]) == ("unknown_workflow", "not-published-anywhere")
    assert await route_after_triage(db, run, actor_id=admin.id) is None
    assert len(await _events(db, run, "routing_failed")) == 1
    runs = (await db.execute(select(func.count()).select_from(WorkflowRun).where(
        WorkflowRun.workflow_key == "not-published-anywhere"))).scalar_one()
    assert runs == 0
