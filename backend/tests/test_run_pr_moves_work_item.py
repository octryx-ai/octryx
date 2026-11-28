"""A workflow run's opened pull request moves its Work item to Review on the board; an epic is not moved
and a done item stays done."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import WorkflowRunEvent, WorkItemStateEvent
from app.models.runtime.secure_work import WorkItem
from app.services.secure_work.lifecycle_transitions import SOURCE_PLATFORM_LIFECYCLE, auto_transition_work_item
from tests.phased_workflow_fixtures import admin_user
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.test_workflow_run_platform_actions import FakeTools, _repository, _run

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("scripted_pool")]

PR_FLOW = {
    "execution_kind": "phased",
    "nodes": [{"id": "start", "type": "start"},
              {"id": "branch", "type": "platform_action", "config": {"action": "scm.create_branch"}},
              {"id": "push", "type": "platform_action", "config": {"action": "scm.push"}},
              {"id": "pr", "type": "platform_action", "config": {"action": "scm.open_pr"}},
              {"id": "ok", "type": "outcome", "config": {"outcome": "done"}},
              {"id": "ko", "type": "outcome", "config": {"outcome": "blocked"}}],
    "edges": [{"id": "1", "source_node_id": "start", "target_node_id": "branch"},
              {"id": "2", "source_node_id": "branch", "target_node_id": "push", "when": "succeeded"},
              {"id": "3", "source_node_id": "branch", "target_node_id": "ko", "when": "failed"},
              {"id": "4", "source_node_id": "push", "target_node_id": "pr", "when": "succeeded"},
              {"id": "5", "source_node_id": "push", "target_node_id": "ko", "when": "failed"},
              {"id": "6", "source_node_id": "pr", "target_node_id": "ok", "when": "succeeded"},
              {"id": "7", "source_node_id": "pr", "target_node_id": "ko", "when": "failed"}],
}


async def _platform_item(db, *, project_id: str | None = None, issue_type: str = "story",
                         work_state: str = "intake") -> WorkItem:
    item = WorkItem(source_type="platform", source_instance="platform", source_key=f"OCX-{uuid.uuid4().hex[:4]}",
                    source_project_key="OCX", title="Hello Kitchen S1", project_id=project_id, work_state=work_state,
                    issue_type=issue_type)
    db.add(item)
    await db.flush()
    return item


async def test_a_platform_item_without_a_definition_moves_along_the_shared_states(db):
    admin = await admin_user(db)
    item = await _platform_item(db)
    result = await auto_transition_work_item(db, item=item, current_user=admin, to_state="review", reason="PR open")
    assert (result["status"], result["from_state"], item.work_state) == ("applied", "intake", "review")
    events = (await db.execute(select(WorkItemStateEvent).where(WorkItemStateEvent.work_item_id == item.id))).scalars()
    assert [(row.from_state, row.to_state, row.source) for row in events] == [
        ("intake", "review", SOURCE_PLATFORM_LIFECYCLE)]
    unknown = await auto_transition_work_item(db, item=item, current_user=admin, to_state="shipped", reason="x")
    assert (unknown["status"], unknown["reason"], item.work_state) == ("skipped", "no_workflow_in_scope", "review")
    done = await _platform_item(db, work_state="done")
    kept = await auto_transition_work_item(db, item=done, current_user=admin, to_state="review", reason="x")
    assert (kept["status"], kept["reason"], done.work_state) == ("skipped", "terminal_state", "done")


@pytest.mark.parametrize(("issue_type", "expected"), [("story", "review"), ("epic", "intake")])
async def test_an_opened_pull_request_moves_the_story_to_review(db, monkeypatch, issue_type, expected):
    from tests.agent_definition_revision_fixtures import make_project

    FakeTools(monkeypatch, {"prepare_github_repository": [{"local_path": "repos/hello"}],
                            "create_github_pull_request": [{"number": 2, "html_url": "https://scm.test/pr/2",
                                                            "status": "created", "reviewers_unresolved": []}]})
    project = await make_project(db)
    await _repository(db, project.id, "github", "hello", owners=["lead-dev"])
    item = await _platform_item(db, project_id=project.id, issue_type=issue_type)
    run = await _run(db, PR_FLOW, work_item_id=item.id, project_id=project.id, repository="github:octryx/hello")
    assert run.outcome == "done", run.context
    assert run.pull_request["url"] == "https://scm.test/pr/2"
    await db.flush()
    state = (await db.execute(select(WorkItem.work_state).where(WorkItem.id == item.id))).scalar_one()
    assert (item.work_state, state) == (expected, expected)
    events = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == "work_state"))).scalars().all()
    assert [event.detail["result"] for event in events] == (["applied"] if issue_type == "story" else [])
