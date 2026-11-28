"""Contract: an intake run reads, closes and counts only the items of its own Workspace."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Project, WorkItem, WorkItemStateEvent
from app.services.secure_work.custom_rest import intake as rest_intake
from app.services.secure_work.servicenow.intake import put_intake
from app.services.secure_work.servicenow.intake import run_intake as run_servicenow
from tests.custom_rest_work_intake_support import _intake as rest_intake_row
from tests.custom_rest_work_intake_support import _world, api, pages, ticket  # noqa: F401 - fixture
from tests.egress_support import public_source_dns  # noqa: F401 - fixture
from tests.jira_intake_support import create_jira_intake, run_jira_intake
from tests.secure_work_jira_sync_support import _issue
from tests.servicenow_intake_support import INCIDENTS_PATH, WritingStub, incident, stub, workspace
from tests.servicenow_stub_support import sys_id

SN_INSTANCE = "servicenow.test"


@pytest.fixture
def sn(monkeypatch):
    instance = WritingStub(incidents=0, changes=0)
    instance.data[INCIDENTS_PATH] = [incident(1, "New"), incident(2, "Resolved")]
    yield from stub(monkeypatch, instance)


async def _other_workspace(db) -> str:
    project = Project(name=f"other-{uuid.uuid4().hex[:8]}", config={})
    db.add(project)
    await db.flush()
    return project.id


async def _foreign_item(db, *, source_type: str, instance: str, key: str, source_id: str | None = None,
                        sync_config_id: str | None = None) -> WorkItem:
    item = WorkItem(project_id=await _other_workspace(db), source_type=source_type, source_instance=instance,
                    source_id=source_id or key, source_key=key, title="Other Workspace item", work_state="development",
                    sync_state="imported", sync_config_id=sync_config_id)
    db.add(item)
    await db.commit()
    return item


async def _untouched(db, item: WorkItem) -> None:
    await db.refresh(item)
    assert (item.work_state, item.sync_state, item.title) == ("development", "imported", "Other Workspace item")
    events = (await db.execute(select(WorkItemStateEvent).where(WorkItemStateEvent.work_item_id == item.id))).all()
    assert events == []


async def _own_items(db, project_id: str) -> list[WorkItem]:
    return list((await db.execute(select(WorkItem).where(WorkItem.project_id == project_id))).scalars())


def _answer(result: dict) -> dict:
    run = {key: value for key, value in result["sync_run"].items()
           if key not in {"id", "created_at", "started_at", "completed_at", "updated_at"}}
    return {**{key: value for key, value in result.items() if key != "sync_run"}, "sync_run": run}


def _immutable(refused: pytest.ExceptionInfo) -> bool:
    return refused.value.status_code == 409 and refused.value.detail["code"] == "workspace_immutable"


async def _servicenow_intake(db):
    project_id, admin = await workspace(db)
    row = await put_intake(db, project_id=project_id, payload={"connection_id": "default"}, user=admin)
    await db.commit()
    return project_id, admin, row


async def test_servicenow_an_open_record_of_another_workspace_previews_as_missing_and_refuses_the_sync(db, sn):
    project_id, admin, row = await _servicenow_intake(db)
    missing = _answer(await run_servicenow(db, row=row, user=admin, dry_run=True))
    foreign = await _foreign_item(db, source_type="servicenow", instance=SN_INSTANCE, key="INC0000001",
                                  source_id=sys_id(1))
    assert _answer(await run_servicenow(db, row=row, user=admin, dry_run=True)) == missing
    await db.commit()
    with pytest.raises(HTTPException) as refused:
        await run_servicenow(db, row=row, user=admin, dry_run=False)
    assert _immutable(refused)
    await db.rollback()
    await _untouched(db, foreign)
    assert await _own_items(db, project_id) == []


async def test_servicenow_a_closed_record_of_another_workspace_answers_like_a_missing_one(db, sn):
    project_id, admin, row = await _servicenow_intake(db)
    foreign = await _foreign_item(db, source_type="servicenow", instance=SN_INSTANCE, key="INC0000002",
                                  source_id=sys_id(2))
    preview = (await run_servicenow(db, row=row, user=admin, dry_run=True))["summary"]
    assert (preview["closed"], preview["skipped_closed"], preview["imported"]) == (0, 1, 1)
    summary = (await run_servicenow(db, row=row, user=admin, dry_run=False))["summary"]
    assert (summary["closed"], summary["skipped_closed"], summary["imported"]) == (0, 1, 1)
    await db.commit()
    await _untouched(db, foreign)
    assert [item.source_key for item in await _own_items(db, project_id)] == ["INC0000001"]


async def test_servicenow_an_older_row_of_another_workspace_never_closes_when_its_record_leaves(db, sn):
    _project_id, admin, row = await _servicenow_intake(db)
    foreign = await _foreign_item(db, source_type="servicenow", instance=SN_INSTANCE, key="INC0000009",
                                  source_id=sys_id(9), sync_config_id=row.id)
    preview = (await run_servicenow(db, row=row, user=admin, dry_run=True))["summary"]
    assert preview["complete"] is True and preview["closed"] == 0
    assert (await run_servicenow(db, row=row, user=admin, dry_run=False))["summary"]["closed"] == 0
    await db.commit()
    await _untouched(db, foreign)


@pytest.mark.usefixtures("public_source_dns")
async def test_custom_rest_an_open_record_of_another_workspace_previews_as_missing_and_refuses_the_sync(
        db, api):  # noqa: F811
    world = await _world(db)
    row = await rest_intake_row(db, world)
    pages(api, [ticket("T-1"), ticket("T-2", "Resolved")])
    missing = _answer(await rest_intake.run_intake(db, row=row, user=world.admin, dry_run=True))
    foreign = await _foreign_item(db, source_type="custom_rest", instance=world.key, key="T-1", source_id="id-T-1")
    assert _answer(await rest_intake.run_intake(db, row=row, user=world.admin, dry_run=True)) == missing
    await db.commit()
    with pytest.raises(HTTPException) as refused:
        await rest_intake.run_intake(db, row=row, user=world.admin, dry_run=False)
    assert _immutable(refused)
    await db.rollback()
    await _untouched(db, foreign)
    assert await _own_items(db, world.project_id) == []


@pytest.mark.usefixtures("public_source_dns")
async def test_custom_rest_a_closed_record_of_another_workspace_answers_like_a_missing_one(db, api):  # noqa: F811
    world = await _world(db)
    row = await rest_intake_row(db, world)
    pages(api, [ticket("T-1"), ticket("T-2", "Resolved")])
    foreign = await _foreign_item(db, source_type="custom_rest", instance=world.key, key="T-2", source_id="id-T-2",
                                  sync_config_id=row.id)
    preview = (await rest_intake.run_intake(db, row=row, user=world.admin, dry_run=True))["summary"]
    assert (preview["closed"], preview["skipped_closed"], preview["imported"]) == (0, 1, 1)
    summary = (await rest_intake.run_intake(db, row=row, user=world.admin, dry_run=False))["summary"]
    assert (summary["closed"], summary["skipped_closed"], summary["imported"]) == (0, 1, 1)
    await db.commit()
    await _untouched(db, foreign)
    assert [item.source_key for item in await _own_items(db, world.project_id)] == ["T-1"]


async def _jira_intake(db) -> dict:
    project = Project(name=f"jira-{uuid.uuid4().hex[:8]}", config={})
    db.add(project)
    await db.commit()
    return await create_jira_intake(db, {"name": "Scoped intake", "project_id": project.id,
                                         "filters": {"project_keys": ["OCX"]}})


@pytest.mark.parametrize("status", ["To Do", "Done"])
async def test_jira_an_issue_of_another_workspace_previews_as_missing_and_refuses_the_sync(db, status):
    config = await _jira_intake(db)
    issues = [_issue("OCX-7000", summary="own"), _issue("OCX-7001", summary="foreign", status=status)]
    missing = _answer(await run_jira_intake(db, config["id"], {"issues": issues}, dry_run=True))
    foreign = await _foreign_item(db, source_type="jira", instance=config["source_instance"], key="OCX-7001")
    assert _answer(await run_jira_intake(db, config["id"], {"issues": issues}, dry_run=True)) == missing
    await db.commit()
    with pytest.raises(HTTPException) as refused:
        await run_jira_intake(db, config["id"], {"issues": issues}, dry_run=False)
    assert _immutable(refused)
    await db.rollback()
    await _untouched(db, foreign)
    assert await _own_items(db, config["project_id"]) == []


async def test_jira_an_older_row_of_another_workspace_is_never_removed_from_the_filter(db):
    config = await _jira_intake(db)
    foreign = await _foreign_item(db, source_type="jira", instance=config["source_instance"], key="OCX-7101",
                                  sync_config_id=config["id"])
    payload = {"issues": [_issue("OCX-7100", summary="own")], "mark_removed_from_filter": True}
    preview = (await run_jira_intake(db, config["id"], payload, dry_run=True))["sync_run"]["summary"]
    assert (preview["would_mark_removed"], preview["would_import"], preview["already_in_work"]) == ([], 1, 0)
    summary = (await run_jira_intake(db, config["id"], payload))["sync_run"]["summary"]
    assert (summary["imported"], summary["removed_from_source_filter"]) == (1, 0)
    await _untouched(db, foreign)


# The competing run executes inside the losing run, right after the losing run read (collision check, Jira prefetch)
# and before it inserts: the interleaving of two concurrent first imports.


async def test_servicenow_a_concurrent_first_import_in_another_workspace_is_the_typed_conflict(db, sn, monkeypatch):
    from app.services.secure_work.intake import pipeline

    winner_project, admin, winner = await _servicenow_intake(db)
    project_id, _admin, row = await _servicenow_intake(db)
    checked = pipeline.require_no_foreign_source_items
    raced: list[bool] = []

    async def competing_import_after_the_check(session, **scope):
        await checked(session, **scope)
        if not raced:
            raced.append(True)
            await run_servicenow(session, row=winner, user=admin, dry_run=False)

    monkeypatch.setattr(pipeline, "require_no_foreign_source_items", competing_import_after_the_check)
    with pytest.raises(HTTPException) as refused:
        await run_servicenow(db, row=row, user=admin, dry_run=False)
    assert raced and _immutable(refused)
    assert [item.source_key for item in await _own_items(db, winner_project)] == ["INC0000001"]
    assert await _own_items(db, project_id) == []


async def _racing_jira(db, monkeypatch, winner: dict, issues: list[dict]) -> list[bool]:
    from app.services.secure_work.jira import jira_sync_records
    from app.services.secure_work.jira.jira_sync import run_jira_work_item_sync
    from tests.jira_intake_support import intake_user

    prefetch = jira_sync_records.existing_items_by_key
    raced: list[bool] = []

    async def competing_import_after_the_prefetch(session, **scope):
        found = await prefetch(session, **scope)
        if not raced:
            raced.append(True)
            await run_jira_work_item_sync(session, config_id=winner["id"], current_user=await intake_user(session),
                                          payload={"issues": issues}, dry_run=False)
        return found

    monkeypatch.setattr(jira_sync_records, "existing_items_by_key", competing_import_after_the_prefetch)
    return raced


async def test_jira_a_concurrent_first_import_in_another_workspace_is_the_typed_conflict(db, monkeypatch):
    winner, config = await _jira_intake(db), await _jira_intake(db)
    assert winner["source_instance"] == config["source_instance"]
    issues = [_issue("OCX-7200", summary="raced")]
    raced = await _racing_jira(db, monkeypatch, winner, issues)
    with pytest.raises(HTTPException) as refused:
        await run_jira_intake(db, config["id"], {"issues": issues})
    assert raced and _immutable(refused)  # the winning row was read: it is in the other Workspace
    assert await _own_items(db, config["project_id"]) == []


async def test_jira_a_concurrent_first_import_in_the_same_workspace_takes_the_update_path(db, monkeypatch):
    winner = await _jira_intake(db)
    config = await create_jira_intake(db, {"name": "Second intake", "project_id": winner["project_id"],
                                           "filters": {"project_keys": ["OCX"]}})
    issues = [_issue("OCX-7300", summary="raced")]
    raced = await _racing_jira(db, monkeypatch, winner, issues)
    summary = (await run_jira_intake(db, config["id"], {"issues": issues}))["sync_run"]["summary"]
    assert raced and (summary.get("imported", 0), summary["unchanged"] + summary.get("updated", 0)) == (0, 1)
    assert [item.source_key for item in await _own_items(db, winner["project_id"])] == ["OCX-7300"]


async def test_a_story_key_synced_into_another_workspace_is_never_taken_or_tied_to_the_epic(db):
    from app.services.workflow_runs.teamwork.stories import _insert_or_synced

    own = await _other_workspace(db)
    epic = WorkItem(project_id=own, source_type="platform", source_instance="octryx", source_key="OCX-8000",
                    title="epic", work_state="intake")
    foreign = await _foreign_item(db, source_type="platform", instance="octryx", key="OCX-8001")
    db.add(epic)
    await db.commit()
    story = WorkItem(project_id=own, source_type="platform", source_instance="octryx", source_key="OCX-8001",
                     title="S1", work_state="intake", epic_key="OCX-8000", parent_key="OCX-8000")
    with pytest.raises(HTTPException) as refused:
        await _insert_or_synced(db, story, epic)
    assert _immutable(refused)
    await db.rollback()
    await db.refresh(foreign)
    assert (foreign.epic_key, foreign.parent_key) == (None, None)


async def test_a_parent_of_another_workspace_gives_no_budget(db):
    from app.services.workflow_runs.limits import inherited_budget

    parent = await _foreign_item(db, source_type="platform", instance="octryx", key="OCX-8100")
    parent.run_limits = {"budget": {"cost_usd": 99}}
    await db.commit()
    story = WorkItem(project_id=await _other_workspace(db), source_type="platform", source_instance="octryx",
                     source_key="OCX-8101", title="story", parent_key="OCX-8100")
    db.add(story)
    await db.flush()
    assert await inherited_budget(db, story) == {}
