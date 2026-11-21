"""DevOps workflows: regression tests for an independent review.

Workspace scope on start, the change-plan guards on a confirmed test contract, run-state concurrency (claim and
re-read, stale turn reports, one platform action per pass), bounded budgets and plan changes, sub-workflow
nesting, the Work item owner and one active run per chat session.
"""

from __future__ import annotations

import copy
import uuid

import pytest
from sqlalchemy import func, select

from app.models import IdentityGroup, Project, ProjectGroup, Session, User, UserGroup, UserProject, WorkflowRun
from app.services.workflow_runs.actions import perform_action
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.limits import pause_run
from app.services.workflow_runs.records import WorkflowRunError, new_chat_session, start_run
from tests.phased_workflow_fixtures import admin_user, phased_definition, publish_phased, run_workspace
from tests.policy_engine_support import bearer, make_user
from tests.test_workflow_run_hitl import contract_definition, drafted_plan, reach_contract
from tests.workflow_run_review_fixes_support import _item


async def _project(db) -> Project:
    project = Project(name=f"Review {uuid.uuid4().hex[:6]}", description="", is_active=True)
    db.add(project)
    await db.flush()
    return project


async def _member(db, project: Project, *, via_group: bool = False) -> User:
    user = await db.get(User, await make_user(db, admin=False))
    if via_group:
        group = IdentityGroup(name=f"g-{uuid.uuid4().hex[:6]}", is_active=True)
        db.add(group)
        await db.flush()
        db.add_all([UserGroup(user_id=user.id, group_id=group.id),
                    ProjectGroup(project_id=project.id, group_id=group.id, role="member")])
    else:
        db.add(UserProject(user_id=user.id, project_id=project.id, role="member"))
    await db.flush()
    return user


@pytest.mark.asyncio
async def test_a_run_starts_only_inside_the_starters_workspace_and_groups_count(client, db):
    """Findings 1 and 11: no run, session or startable list in a foreign Workspace; group members belong."""
    project = await _project(db)
    key = await publish_phased(db, phased_definition())
    item = await _item(db, project)
    outsider = await db.get(User, await make_user(db, admin=False))
    member = await _member(db, project, via_group=True)
    await db.commit()

    headers = bearer(outsider.id)
    foreign = await client.post("/api/v1/workflow-runs", headers=headers,
                                json={"workflow_key": key, "project_id": project.id})
    # A foreign Workspace answers like one that does not exist.
    assert foreign.status_code == 409 and foreign.json()["detail"]["code"] == "workspace_required"
    anchored = await client.post("/api/v1/workflow-runs", headers=headers,
                                 json={"workflow_key": key, "work_item_id": item.id})
    assert anchored.status_code == 403 and anchored.json()["detail"]["code"] == "work_item_scope"
    listed = await client.get(f"/api/v1/workflow-runs/startable?project_id={project.id}", headers=headers)
    assert listed.status_code == 404  # the answer of an unknown Workspace
    sessions = (await db.execute(select(func.count()).select_from(Session).where(Session.user_id == outsider.id)))
    assert sessions.scalar() == 0

    started = await client.post("/api/v1/workflow-runs", headers=bearer(member.id),
                                json={"workflow_key": key, "work_item_id": item.id})
    assert started.status_code == 200, started.text
    limits = await client.put(f"/api/v1/workflow-runs/work-items/{item.id}/limits", headers=bearer(member.id),
                              json={"loop_limit": 2})
    assert limits.status_code == 200


@pytest.mark.asyncio
async def test_confirming_a_test_contract_keeps_the_change_plan_routes_guards(db):
    """Finding 2: a requester without the work operator role cannot approve the change plan through a run."""
    project = await _project(db)
    requester = await _member(db, project)
    item = await _item(db, project)
    key = await publish_phased(db, contract_definition())
    session = await new_chat_session(db, requester, project.id)
    run = await start_run(db, user=requester, workflow_key=key, work_item_id=item.id, session=session)
    await reach_contract(db, run, session)  # the run drafts the plan; approving it keeps its guards
    plan = await drafted_plan(db, run)
    waiting = run.node_state["waiting"]

    with pytest.raises(WorkflowRunError) as refused:
        await perform_action(db, run, user=requester, body={"action": "confirm",
                                                             "payload_hash": waiting["payload_hash"]})
    assert (refused.value.code, refused.value.status_code) == ("test_contract_refused", 403)
    assert plan.status == "ready_for_review" and run.current_node_id == "contract"


@pytest.mark.asyncio
async def test_the_work_item_owner_continues_a_paused_run_but_does_not_abort_it(client, db):
    """Requester or Work item owner continue; other members only read."""
    project = await _project(db)
    owner = await _member(db, project)
    other = await _member(db, project)
    item = await _item(db, project, assignee=owner.username)
    requester = await _member(db, project)
    key = await publish_phased(db, phased_definition(max_iterations=1))
    workspace_id = await run_workspace(db, requester, item.id)
    run = await start_run(db, user=requester, workflow_key=key, project_id=workspace_id, work_item_id=item.id)
    await pause_run(db, run, reason="loop_limit", actor_id=None,
                    detail={"edge_id": "rework", "resume": {"kind": "stay"}})
    await db.commit()

    read_only = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=bearer(other.id),
                                  json={"action": "continue", "k": 1})
    assert read_only.status_code == 403
    view = (await client.get(f"/api/v1/workflow-runs/{run.id}", headers=bearer(owner.id))).json()["run"]
    assert view["access"] == "write" and "abort" not in {action["key"] for action in view["actions"]}
    aborted = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=bearer(owner.id),
                                json={"action": "abort", "reason": "not mine"})
    assert aborted.status_code == 403
    continued = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=bearer(owner.id),
                                  json={"action": "continue", "k": 1})
    assert continued.status_code == 200, continued.text
    assert continued.json()["run"]["status"] == "running"


@pytest.mark.asyncio
async def test_a_chat_already_following_an_active_run_is_not_taken_over_silently(db):
    """Finding 13."""
    admin = await admin_user(db)
    key = await publish_phased(db, copy.deepcopy(phased_definition()))
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    first = await start_run(db, user=admin, workflow_key=key, project_id=workspace_id, session=session)
    with pytest.raises(WorkflowRunError) as bound:
        await start_run(db, user=admin, workflow_key=key, project_id=workspace_id, session=session)
    assert (bound.value.code, bound.value.status_code) == ("session_bound", 409)
    assert (await run_turn_resolution(db, session, user_message="Go."))["workflow_run"]["run_id"] == (
        first.id)


@pytest.mark.asyncio
async def test_a_run_never_starts_in_an_inactive_workspace(client, db):
    """The gateway refuses every model call of an inactive Workspace, so a run there is refused at the start."""
    project = await _project(db)
    project.is_active = False
    key = await publish_phased(db, phased_definition())
    member = await _member(db, project, via_group=False)
    await db.commit()

    refused = await client.post("/api/v1/workflow-runs", headers=bearer(member.id),
                                json={"workflow_key": key, "project_id": project.id})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "workspace_inactive"
    assert refused.json()["detail"]["message"] == f"Workspace {project.name} is inactive. Activate it under Admin → Workspaces."
    assert (await db.execute(select(func.count()).select_from(WorkflowRun).where(
        WorkflowRun.project_id == project.id))).scalar_one() == 0
