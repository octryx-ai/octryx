"""A workflow run moves a Jira Work item without a write-back definition by Jira's status category.

Without a write-back definition in scope, spec-writing and epic-delivery would leave the epic and its stories in
Intake on the board and "To Do" in Jira even after their pull requests opened. So:

- the default picks the transition Jira offers into ``indeterminate`` (review prefers a "review" status, then
  "progress"; development prefers "progress"); nothing fitting clearly is no Jira write, the board moves anyway;
- an issue outside ``jira_allowed_projects`` gets no request at all;
- an opened pull request moves the Jira story to Review and its epic to development, recorded as run events.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.models import WorkflowRunEvent, WorkItemStateEvent
from app.models.runtime.secure_work import WorkItem
from app.services.secure_work.jira import jira_default_states
from app.services.secure_work.jira.jira_default_states import move_by_status_category, pick_transition
from tests.phased_workflow_fixtures import admin_user
from tests.test_run_pr_moves_work_item import PR_FLOW
from tests.test_workflow_run_platform_actions import FakeTools, _repository, _run

TO_DO, IN_PROGRESS, DONE = "new", "indeterminate", "done"


def _offer(tid: str, name: str, category: str) -> dict:
    return {"id": tid, "name": name, "to": {"name": name, "statusCategory": {"key": category}}}


SIMPLE = [_offer("11", "To Do", TO_DO), _offer("21", "In Progress", IN_PROGRESS), _offer("31", "Done", DONE)]
WITH_REVIEW = [*SIMPLE, _offer("41", "In Review", IN_PROGRESS)]


def test_the_default_target_is_chosen_from_what_jira_offers():
    assert pick_transition(WITH_REVIEW, "review")["id"] == "41"
    assert pick_transition(SIMPLE, "review")["id"] == "21"  # no review status: In Progress
    assert pick_transition(WITH_REVIEW, "development")["id"] == "21"
    assert pick_transition(WITH_REVIEW, "review", "In Review")["id"] == "21"  # never the status it already has
    assert pick_transition(SIMPLE, "review", "In Progress") is None  # already there, nothing else in progress
    unclear = [_offer("51", "Doing", IN_PROGRESS), _offer("52", "Testing", IN_PROGRESS)]
    assert pick_transition(unclear, "review") is None  # several without a fitting name: never a guess
    assert pick_transition(unclear[:1], "review")["id"] == "51"  # the only one into the category
    assert pick_transition(WITH_REVIEW, "done") is None  # done is the person's merge, never set here


def _key() -> str:
    return f"CHEF-{uuid.uuid4().int % 90000 + 100}"


async def _jira_item(db, *, key: str = "", project_id: str | None = None, issue_type: str = "story",
                     epic_key: str | None = None, work_state: str = "intake") -> WorkItem:
    item = WorkItem(source_type="jira", source_instance="chef-cloud", source_key=key or _key(),
                    source_project_key="CHEF", title="Hello Kitchen", source_status="To Do", work_state=work_state,
                    sync_state="unchanged", project_id=project_id, issue_type=issue_type, epic_key=epic_key)
    db.add(item)
    await db.flush()
    return item


def _fake_jira(monkeypatch, offers: list[dict], *, allowed=frozenset({"CHEF"})) -> list[tuple[str, str, dict]]:
    calls: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        calls.append((request.method, request.url.path, body))
        return httpx.Response(200, json={"transitions": offers}) if request.method == "GET" else httpx.Response(204)

    async def access(_item, _db):
        return "https://mm.atlassian.test", {"Authorization": "Basic x"}, True, allowed, None

    monkeypatch.setattr(jira_default_states, "_jira_access", access)
    monkeypatch.setattr(jira_default_states, "egress_transport", lambda _name: httpx.MockTransport(handler))
    return calls


@pytest.mark.asyncio
async def test_a_jira_item_without_a_definition_moves_jira_and_the_board(db, monkeypatch):
    calls = _fake_jira(monkeypatch, WITH_REVIEW)
    admin = await admin_user(db)
    item = await _jira_item(db)
    result = await move_by_status_category(db, item, current_user=admin, to_state="review", reason="PR open")
    assert (result["status"], result["jira"]["status"], item.work_state, item.source_status) == (
        "applied", "executed", "review", "In Review")
    assert [(method, body) for method, _path, body in calls] == [("GET", {}), ("POST", {"transition": {"id": "41"}})]
    event = (await db.execute(select(WorkItemStateEvent).where(WorkItemStateEvent.work_item_id == item.id))).scalar_one()
    assert (event.from_state, event.to_state, event.source, event.jira_sync_preview_json["will_mutate_jira"]) == (
        "intake", "review", "platform_lifecycle", True)
    again = await move_by_status_category(db, item, current_user=admin, to_state="review", reason="again")
    assert again["status"] == "unchanged" and len(calls) == 2


@pytest.mark.asyncio
async def test_an_issue_outside_the_allowed_projects_gets_no_request(db, monkeypatch):
    calls = _fake_jira(monkeypatch, SIMPLE, allowed=frozenset({"BRD"}))
    admin = await admin_user(db)
    item = await _jira_item(db)
    result = await move_by_status_category(db, item, current_user=admin, to_state="review", reason="PR open")
    assert (result["jira"]["status"], item.work_state, item.source_status, calls) == (
        "scope_not_allowed", "review", "To Do", [])
    done = await _jira_item(db, work_state="done")
    kept = await move_by_status_category(db, done, current_user=admin, to_state="review", reason="x")
    assert (kept["reason"], done.work_state) == ("terminal_state", "done")


@pytest.mark.asyncio
async def test_an_opened_pull_request_moves_the_jira_story_to_review_and_its_epic_to_development(db, monkeypatch):
    from tests.agent_definition_revision_fixtures import make_project

    calls = _fake_jira(monkeypatch, SIMPLE)
    FakeTools(monkeypatch, {"prepare_github_repository": [{"local_path": "repos/hello"}],
                            "create_github_pull_request": [{"number": 10, "html_url": "https://scm.test/pr/10",
                                                            "status": "created", "reviewers_unresolved": []}]})
    project = await make_project(db)
    await _repository(db, project.id, "github", "hello", owners=["lead-dev"])
    epic = await _jira_item(db, key=_key(), project_id=project.id, issue_type="epic")
    story = await _jira_item(db, project_id=project.id, epic_key=epic.source_key)
    run = await _run(db, PR_FLOW, work_item_id=story.id, project_id=project.id, repository="github:octryx/hello")
    assert run.outcome == "done", run.context
    await db.flush()
    assert (story.work_state, epic.work_state) == ("review", "development")
    assert sum(1 for method, _p, _b in calls if method == "POST") == 2  # both moved in Jira (In Progress)
    events = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == "work_state"))).scalars().all()
    assert [(e.detail["item"], e.detail["to_state"], e.detail["result"], e.detail["jira"]["status"])
            for e in events] == [(story.source_key, "review", "applied", "executed"),
                                 (epic.source_key, "development", "applied", "executed")]
