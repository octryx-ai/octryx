"""The coordinator splits an epic into stories; the server creates them and the chain builds them in that order.

The flow: ``story_plan`` → ``work.create_stories`` → ``context.stories`` → the epic chain.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import WorkflowRun
from app.models.runtime.secure_work import WorkItem
from app.services.workflow_runs import epic_chain
from app.services.workflow_runs.platform.dispatch import APPROVAL_PENDING, SUCCEEDED, ToolOutcome
from app.services.workflow_runs.teamwork import stories as stories_module
from app.services.workflow_runs.teamwork.stories import create_stories, validate_story_plan
from tests.agent_definition_revision_fixtures import make_member, make_project
from tests.phased_workflow_fixtures import admin_user

PLAN = {"stories": [
    {"title": "Design system and app shell", "goal": "The app's look", "criteria": ["tokens exist"],
     "spec_sections": ["2 Design"]},
    {"title": "Search dishes", "goal": "Find a dish", "criteria": ["search returns dishes"],
     "depends_on_titles": ["Design system and app shell"]},
]}


def _story(title, **extra):
    return {"title": title, "goal": "g", "criteria": ["c"], **extra}


# --- the validator -------------------------------------------------------------------------------------------------


def test_a_valid_plan_is_recorded_in_build_order():
    record, problems = validate_story_plan(PLAN)
    assert problems == []
    assert [story["title"] for story in record["stories"]] == ["Design system and app shell", "Search dishes"]
    assert record["stories"][1]["depends_on_titles"] == ["Design system and app shell"]


@pytest.mark.parametrize(("raw", "expected"), [
    ({}, "at least one story"),
    ({"stories": []}, "at least one story"),
    ({"stories": [_story("")]}, "title is required"),
    ({"stories": [_story("A"), _story("a")]}, "used twice"),
    ({"stories": [{"title": "A", "criteria": []}]}, "at least one acceptance criterion"),
    ({"stories": [_story("A", depends_on_titles=["B"]), _story("B")]}, "no story before it"),
    ({"stories": [_story("A", depends_on_titles=["A"])]}, "no story before it"),
])
def test_a_plan_is_refused_with_its_problem(raw, expected):
    _record, problems = validate_story_plan(raw)
    assert any(expected in problem for problem in problems), problems


def test_every_problem_is_listed_and_no_story_count_is_refused():
    _record, problems = validate_story_plan({"stories": [_story(""), {"title": "B"}, _story("C", depends_on_titles=[
        "Z"])]})
    assert len(problems) == 3
    many = {"stories": [_story(f"S{n}") for n in range(40)]}  # no artificial limit
    assert validate_story_plan(many)[1] == []


# --- work.create_stories -------------------------------------------------------------------------------------------


async def _epic_run(db, *, source_type="jira", key="OPS-1", context=None):
    admin = await admin_user(db)
    project = await make_project(db)
    await make_member(db, admin, project, "owner")
    epic = WorkItem(source_type=source_type, source_instance="cloud" if source_type == "jira" else "platform",
                    source_project_key=key.split("-")[0], source_key=key, title="Kitchen helper", issue_type="Epic",
                    project_id=project.id, work_state="intake")
    db.add(epic)
    await db.flush()
    run = WorkflowRun(project_id=project.id, work_item_id=epic.id, workflow_kind="phased", workflow_key="spec-writing",
                      title="Kitchen helper", requested_by=admin.id, status="running",
                      context={"outputs": {"story_plan": {"record": validate_story_plan(PLAN)[0]}}, **(context or {})})
    db.add(run)
    await db.flush()
    return admin, project, epic, run


def _fake_jira(calls, *, pending_at=None):
    async def dispatch(_db, _run, tool, arguments, *, capability_class, **_kwargs):
        calls.append((tool, arguments, capability_class))
        if pending_at is not None and len(calls) == pending_at:
            return ToolOutcome(APPROVAL_PENDING, {}, "waits", "approval-1")
        return ToolOutcome(SUCCEEDED, {"ticket_id": f"OPS-{10 + len(calls)}", "id": str(len(calls)),
                                       "status": "created"})
    return dispatch


@pytest.mark.asyncio
async def test_a_jira_epic_gets_its_stories_with_parent_and_work_items_with_epic_key(db, monkeypatch):
    _admin, _project, epic, run = await _epic_run(db)
    calls = []
    monkeypatch.setattr(stories_module, "dispatch_tool", _fake_jira(calls))

    outcome = await create_stories(db, run, {"story_workflow": "team-delivery"})

    assert outcome.ok and outcome.result["stories"] == ["OPS-11", "OPS-12"]
    assert [(tool, args["parent_key"], args["issue_type"], args["summary"]) for tool, args, _cls in calls] == [
        ("create_jira_ticket", "OPS-1", "Story", "Design system and app shell"),
        ("create_jira_ticket", "OPS-1", "Story", "Search dishes")]
    assert {cls for _t, _a, cls in calls} == {"deliver"}
    assert "- search returns dishes" in calls[1][1]["description"]
    items = (await db.execute(select(WorkItem).where(WorkItem.epic_key == "OPS-1"))).scalars().all()
    assert sorted((item.source_key, item.source_instance, item.parent_key) for item in items) == [
        ("OPS-11", "cloud", "OPS-1"), ("OPS-12", "cloud", "OPS-1")]
    assert run.context["stories"] == ["OPS-11", "OPS-12"]
    assert run.context["story_workflow"] == "team-delivery"
    assert epic.source_key == "OPS-1"


@pytest.mark.asyncio
async def test_a_held_approval_creates_only_the_rest_when_the_step_runs_again(db, monkeypatch):
    _admin, _project, _epic, run = await _epic_run(db)
    calls = []
    monkeypatch.setattr(stories_module, "dispatch_tool", _fake_jira(calls, pending_at=2))
    first = await create_stories(db, run, {})
    assert first.state == APPROVAL_PENDING and "stories" not in run.context
    second = await create_stories(db, run, {})
    assert second.ok and [args["summary"] for _t, args, _c in calls] == [
        "Design system and app shell", "Search dishes", "Search dishes"]
    assert run.context["stories"] == ["OPS-11", "OPS-13"]


@pytest.mark.asyncio
async def test_a_platform_epic_gets_platform_stories(db, monkeypatch):
    _admin, project, _epic, run = await _epic_run(db, source_type="platform", key="OCX-90")

    async def never(*_a, **_k):
        raise AssertionError("no Jira for a platform epic")

    monkeypatch.setattr(stories_module, "dispatch_tool", never)
    run.context = {**run.context}
    epic = await db.get(WorkItem, run.work_item_id)
    epic.issue_type = "epic"
    outcome = await create_stories(db, run, {})
    assert outcome.ok
    created = [await _by_key(db, key) for key in run.context["stories"]]
    assert [(item.title, item.epic_key, item.source_type) for item in created] == [
        ("Design system and app shell", "OCX-90", "platform"), ("Search dishes", "OCX-90", "platform")]


async def _by_key(db, key):
    return (await db.execute(select(WorkItem).where(WorkItem.source_key == key))).scalar_one()


@pytest.mark.asyncio
async def test_an_epic_that_has_stories_adopts_them_and_creates_none(db, monkeypatch):
    _admin, project, _epic, run = await _epic_run(db, context={"story_workflow": "epic-delivery"})
    db.add(WorkItem(source_type="jira", source_instance="cloud", source_key="OPS-5", title="Made by a person",
                    epic_key="OPS-1", project_id=project.id, work_state="intake"))
    await db.flush()

    async def never(*_a, **_k):
        raise AssertionError("nothing is created")

    monkeypatch.setattr(stories_module, "dispatch_tool", never)
    outcome = await create_stories(db, run, {"story_workflow": "team-delivery"})
    assert outcome.ok and outcome.result == {"status": "adopted", "stories": ["OPS-5"]}
    assert run.context["stories"] == ["OPS-5"]
    assert run.context["story_workflow"] == "epic-delivery"  # the run's own choice stays


@pytest.mark.asyncio
async def test_no_plan_or_no_epic_fails_with_its_reason(db):
    _admin, _project, epic, run = await _epic_run(db)
    run.context = {}
    assert "no story plan" in (await create_stories(db, run, {})).reason
    epic.issue_type = "Story"
    assert "no epic" in (await create_stories(db, run, {})).reason


def test_the_action_is_definition_only_and_needs_a_story_plan_before_it():
    from app.services.workflow_runs.data_flow import consumes
    from app.services.workflow_runs.graph import PhasedNode
    from app.services.workflow_runs.platform.catalog import ACTIONS, WORK_CREATE_STORIES, validate_action_config

    assert not ACTIONS[WORK_CREATE_STORIES].requestable
    assert validate_action_config("stories", {"action": WORK_CREATE_STORIES,
                                              "params": {"story_workflow": "team-delivery"}}) == []
    node = PhasedNode(id="stories", kind="platform_action", title="Stories",
                      config={"action": WORK_CREATE_STORIES})
    assert "story_plan" in consumes(node)


# --- the chain builds the stories in the stored order --------------------------------------------------------------


def _recording_start(project, admin, started):
    async def fake_start(db_, **kwargs):
        run = WorkflowRun(project_id=project.id, work_item_id=kwargs["work_item_id"], workflow_kind="phased",
                          workflow_key=kwargs["workflow_key"], title="x", requested_by=admin.id, status="running",
                          context=kwargs["context"])
        db_.add(run)
        await db_.flush()
        started.append(kwargs)
        return run
    return fake_start


@pytest.mark.asyncio
async def test_the_chain_starts_the_stories_in_the_stored_order(db, monkeypatch):
    """X-10 was created before X-9 (or in the same second): the stored order wins over creation time and key."""
    admin, project, epic, _run = await _epic_run(db, key="X-1")
    s10 = WorkItem(source_type="jira", source_instance="cloud", source_key="X-10", title="second", epic_key="X-1",
                   project_id=project.id, work_state="intake")
    db.add(s10)
    await db.flush()
    s9 = WorkItem(source_type="jira", source_instance="cloud", source_key="X-9", title="first", epic_key="X-1",
                  project_id=project.id, work_state="intake")
    db.add(s9)
    await db.flush()
    started = []
    monkeypatch.setattr("app.services.workflow_runs.records.start_run", _recording_start(project, admin, started))
    # Not ``spec-writing``: any run of the epic that recorded its stories drives the chain.
    split = WorkflowRun(project_id=project.id, work_item_id=epic.id, workflow_kind="phased", workflow_key="epic-split",
                        title="Kitchen helper", requested_by=admin.id, status="completed", outcome="done",
                        branch="docs/X-1-spec",
                        context={"stories": ["X-9", "X-10"], "story_workflow": "team-delivery"})
    db.add(split)
    await db.flush()
    first = await epic_chain.continue_epic(db, split, actor_id=None)
    assert first.work_item_id == s9.id and started[-1]["workflow_key"] == "team-delivery"
    assert started[-1]["context"]["epic_chain"]["stories"] == ["X-9", "X-10"]
    first.status, first.outcome, first.branch = "completed", "done", "feature/X-9-first"
    second = await epic_chain.continue_epic(db, first, actor_id=None)
    assert second.work_item_id == s10.id and started[-1]["workflow_key"] == "team-delivery"
    assert started[-1]["context"]["base_branch"] == "feature/X-9-first"
