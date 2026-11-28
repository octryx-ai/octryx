"""Anti-slop D: a pull request links to its run, session and approved plan, and they list the pull request back."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Session, WorkflowRunSession, WorkItem, WorkPullRequest
from app.models.runtime.secure_work import WorkChangePlan
from app.services.agent_board.handoffs import validate_sections, write_handoff
from app.services.ai_marking import MARKER_PREFIX
from app.services.ai_marking_tools import marked_arguments
from app.services.data_access import as_viewer
from app.services.project.private_workspace import ensure_private_workspace
from app.services.workflow_runs import pr_links
from app.services.workflow_runs.plan_scope import plan_hash
from app.services.workflow_runs.platform import scm
from app.tools.context import ToolContext
from app.web._helpers.chat_session_view import build_chat_session_view
from tests.devices.device_support import user_named
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.linked_accounts_support import _cloud_run, _scripted
from tests.phased_workflow_fixtures import admin_user

pytestmark = pytest.mark.asyncio

ORIGIN = "https://octryx.example"
RECORDED_PLAN = {"parts": ["Add the totals row", "Show it in the report"], "paths": ["backend/app/totals.py"],
                 "endpoints": [], "expensive": [], "risks": [], "open_questions": []}
PR_URL = "https://bitbucket.org/acme/payments/pull-requests/7"


@pytest.fixture(autouse=True)
def _origin(monkeypatch):
    monkeypatch.setattr(pr_links, "_origin", lambda: ORIGIN)


async def _run_and_session(db, owner, *, context=None):
    run = await _cloud_run(db, owner)
    run.context = dict(context or {})
    session = Session(id=str(uuid.uuid4()), user_id=owner.id, project_id=run.project_id, origin="chat")
    db.add(session)
    await db.flush()
    db.add(WorkflowRunSession(run_id=run.id, session_id=session.id, role="main", active=True))
    await db.flush()
    return run, session


async def _approved_work_plan(db, run, owner) -> WorkChangePlan:
    item = WorkItem(id=str(uuid.uuid4()), project_id=run.project_id, source_key="PAY-1", title="Totals")
    db.add(item)
    await db.flush()
    plan = WorkChangePlan(work_item_id=item.id, version=2, status="approved", title="Totals plan", created_by=owner.id)
    db.add(plan)
    await db.flush()
    run.work_item_id = item.id
    run.context = {**dict(run.context or {}), "change_plan": {"id": plan.id}}
    return plan


async def _opened_description(db, monkeypatch, run) -> str:
    calls = _scripted(monkeypatch, {"id": 7, "url": PR_URL, "status": "created", "reviewers_unresolved": []})
    outcome = await scm.open_pr(db, run, {})
    assert outcome.ok, outcome.reason
    return next(arguments for tool, arguments in calls if tool == "create_bitbucket_pull_request")["description"]


async def test_a_run_pull_request_links_run_session_and_the_recorded_plan(db, monkeypatch):
    admin = await admin_user(db)
    run, session = await _run_and_session(db, admin, context={"outputs": {"change_plan": {"record": RECORDED_PLAN}}})

    body = await _opened_description(db, monkeypatch, run)

    assert body.endswith(
        f"Octryx links\n- Run: {ORIGIN}/api/v1/workflow-runs/{run.id}\n- Session: {ORIGIN}/chat?session_id={session.id}"
        f"\n- Approved plan ({plan_hash(RECORDED_PLAN)}): 2 part(s): Add the totals row; Show it in the report"
        " · paths: backend/app/totals.py")


async def test_a_run_pull_request_names_the_approved_work_plan_and_records_its_run_and_session(db, monkeypatch):
    from app.services.workflow_runs.confirmation_payloads import plan_hash as work_plan_hash

    admin = await admin_user(db)
    run, session = await _run_and_session(db, admin)
    plan = await _approved_work_plan(db, run, admin)

    body = await _opened_description(db, monkeypatch, run)

    assert f"- Approved plan: Totals plan v2 ({work_plan_hash(plan)})" in body
    row = (await db.execute(select(WorkPullRequest).where(WorkPullRequest.pr_url == PR_URL))).scalar_one()
    assert (row.session_id, row.run_id) == (session.id, run.id)


async def test_a_run_pull_request_without_an_approved_plan_has_only_the_links(db, monkeypatch):
    admin = await admin_user(db)
    unapproved = {**RECORDED_PLAN, "expensive": ["migrations"]}
    run, session = await _run_and_session(db, admin, context={"outputs": {"change_plan": {"record": unapproved}}})

    body = await _opened_description(db, monkeypatch, run)

    assert body.endswith(f"- Session: {ORIGIN}/chat?session_id={session.id}") and "plan" not in body.lower()


async def test_an_agent_pull_request_carries_the_session_link_and_plan_once(db, monkeypatch):
    import app.tools.registry as registry

    admin = await admin_user(db)
    run, session = await _run_and_session(db, admin, context={"outputs": {"change_plan": {"record": RECORDED_PLAN}}})
    seen: list[dict] = []

    async def gate(tool_name, params, context):
        seen.append(params)
        return {"error": "blocked for the test"}

    monkeypatch.setattr(registry, "_run_governed_tool_checks", gate)
    context = ToolContext(user_id=admin.id, project_ids=[run.project_id], roles=[], session_id=session.id,
                          project_config={}, db=db)
    await registry.execute_tool("create_github_pull_request", {"title": "Totals", "description": "Adds totals"},
                                context)

    body = seen[0]["description"]
    assert body.startswith(f"Adds totals\n\nOctryx links\n- Run: {ORIGIN}/api/v1/workflow-runs/{run.id}\n"
                           f"- Session: {ORIGIN}/chat?session_id={session.id}\n- Approved plan (")
    assert body.splitlines()[-1].startswith(f"— {MARKER_PREFIX}")
    assert await marked_arguments("create_github_pull_request", seen[0], context) == seen[0]


async def test_a_comment_or_a_call_without_a_session_gets_no_links(db):
    admin = await admin_user(db)
    run, session = await _run_and_session(db, admin)
    context = ToolContext(user_id=admin.id, project_ids=[], roles=[], session_id=session.id, project_config={}, db=db)
    comment = await marked_arguments("add_bitbucket_pull_request_comment", {"text": "Done"}, context)
    unknown = ToolContext(user_id=admin.id, project_ids=[], roles=[], session_id="no-run", project_config={}, db=db)

    assert "Octryx links" not in comment["text"]
    assert await pr_links.with_session_links({"description": "x"}, unknown) == {"description": "x"}


async def test_the_session_view_lists_the_sessions_pull_requests(db, monkeypatch):
    admin = await admin_user(db)
    run, session = await _run_and_session(db, admin)
    await _approved_work_plan(db, run, admin)
    await _opened_description(db, monkeypatch, run)

    view = await build_chat_session_view(db, user=admin, session_id=session.id)

    assert view["selectedSessionPullRequests"] == [{"url": PR_URL, "title": "PAY-1: Totals", "state": "open",
                                                    "run_id": run.id}]


async def test_a_handoff_carries_the_items_pull_requests_and_plan_and_a_client_cannot_send_them(db, monkeypatch):
    admin = await admin_user(db)
    run, session = await _run_and_session(db, admin)
    plan = await _approved_work_plan(db, run, admin)
    await _opened_description(db, monkeypatch, run)
    item = await db.get(WorkItem, run.work_item_id)

    handoff = await write_handoff(db, item=item, sections={}, author_kind="human", author_user_id=admin.id,
                                  author_agent_hash=None)

    assert handoff.sections["pull_requests"] == [{"url": PR_URL, "state": "open", "session_id": session.id,
                                                  "run_id": run.id}]
    assert {key: handoff.sections["plan"][key] for key in ("id", "version", "status")} == (
        {"id": plan.id, "version": 2, "status": "approved"})
    for key in ("pull_requests", "plan"):
        with pytest.raises(HTTPException) as refused:
            validate_sections({key: []})
        assert refused.value.detail == {"code": "handoff_invalid", "field": key}


async def test_a_person_outside_a_private_workspace_cannot_list_its_sessions_pull_requests(db):
    # Work items cannot live in a private Workspace, so the PR's item is a team Workspace's: the session hides it.
    owner = await user_named(db, f"pr-owner-{uuid.uuid4().hex[:6]}")
    outsider = await user_named(db, f"pr-outsider-{uuid.uuid4().hex[:6]}")
    workspace = await ensure_private_workspace(db, owner)
    team = await seed_workspace(db)
    session = Session(id=str(uuid.uuid4()), user_id=owner.id, project_id=workspace.id, origin="chat")
    item = WorkItem(id=str(uuid.uuid4()), project_id=team, source_key="PRV-1", title="Team item")
    db.add_all([session, item])
    await db.flush()
    db.add(WorkPullRequest(work_item_id=item.id, scope_key=team, repository_slug="acme/private", pr_id="3",
                           pr_url="https://git.example/acme/private/pull/3", session_id=session.id,
                           created_by=owner.id))
    await db.commit()

    with as_viewer(outsider.id):
        assert await pr_links.session_pull_requests(db, session.id) == []
    with as_viewer(owner.id):
        assert [entry["url"] for entry in await pr_links.session_pull_requests(db, session.id)] == [
            "https://git.example/acme/private/pull/3"]
