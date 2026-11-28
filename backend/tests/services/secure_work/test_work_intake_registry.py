"""One intake pipeline with a source registry instead of seven closed Jira/ServiceNow lists."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Task, WorkItem
from app.services.secure_work.intake.registry import (
    CODE_UNKNOWN_SOURCE,
    GENERIC_SYNC_TASK_TYPE,
    require_source,
    source_for,
    sync_task_types,
)
from app.services.secure_work.intake.scheduled import run_scheduled_intake
from app.services.secure_work.item_connection import (
    UnknownItemSourceError,
    item_scope_key,
    work_item_connection_config,
)
from app.services.secure_work.servicenow.intake import (
    SERVICENOW_SYNC_TASK_TYPE,
    put_intake,
)
from app.services.secure_work.sync_policy import executes
from app.services.secure_work.workflow_mapping import (
    _normalize_sync_policy,
    normalize_workflow_mappings,
    normalize_workflow_states,
)
from tests.servicenow_intake_support import INCIDENTS_PATH, WritingStub, incident, stub, workspace


@pytest.fixture
def sn(monkeypatch):
    instance = WritingStub(incidents=0, changes=0)
    instance.data[INCIDENTS_PATH] = [incident(1, "New"), incident(2, "In Progress")]
    yield from stub(monkeypatch, instance)


def test_the_registry_knows_both_sources_and_refuses_an_unknown_one():
    assert source_for("jira").label == "Jira" and source_for("servicenow").label == "ServiceNow"
    assert {"secure_work_jira_sync", SERVICENOW_SYNC_TASK_TYPE, GENERIC_SYNC_TASK_TYPE} <= sync_task_types()
    assert source_for("gitlab") is None
    with pytest.raises(HTTPException) as refused:
        require_source("gitlab")
    assert refused.value.status_code == 422 and refused.value.detail["code"] == CODE_UNKNOWN_SOURCE


async def test_the_item_scope_key_comes_from_the_source_and_an_unknown_one_is_refused(db):
    jira = WorkItem(source_type="jira", source_key="BRD-7")
    record = WorkItem(source_type="servicenow", source_key="INC1", issue_type="incident",
                      source_fields_json={"servicenow": {"table": "change_request"}})
    assert item_scope_key(jira, "jira") == "BRD"
    assert item_scope_key(record, "servicenow") == "change_request"
    other = WorkItem(source_type="gitlab", source_key="G-1", issue_type="incident")
    with pytest.raises(UnknownItemSourceError):
        item_scope_key(other, "gitlab")
    assert await work_item_connection_config(db, other, "gitlab") == ({}, "source_unknown")


async def test_the_generic_task_type_runs_the_intake_of_its_source(db, sn):
    project_id, admin = await workspace(db)
    row = await put_intake(db, project_id=project_id, payload={"connection_id": "default"}, user=admin)
    await db.commit()
    task = Task(dispatch_binding="task_definition", name="generic", task_type=GENERIC_SYNC_TASK_TYPE, config={"sync_config_id": row.id},
                owner_id=admin.id, project_id=project_id)
    run = SimpleNamespace(output=None)
    output = await run_scheduled_intake(db, task=task, task_run=run)
    assert output["summary"]["imported"] == 2 and run.output is output
    assert {item.source_key for item in (await db.execute(
        select(WorkItem).where(WorkItem.project_id == project_id))).scalars()} == {"INC0000001", "INC0000002"}


async def test_the_scheduled_servicenow_sync_starts_the_automatic_analyses(db, sn, monkeypatch):
    project_id, admin = await workspace(db)
    row = await put_intake(db, project_id=project_id, payload={"connection_id": "default", "schedule": {"preset": "every_15_min"}}, user=admin)
    await db.commit()
    task = (await db.execute(select(Task).where(Task.task_type == SERVICENOW_SYNC_TASK_TYPE))).scalars().all()
    task = next(entry for entry in task if entry.config["sync_config_id"] == row.id)
    calls = []

    async def after_sync(db, *, project_id, source_type, actor):
        calls.append((project_id, source_type, actor.id))
        return {"started": 1, "results": []}

    monkeypatch.setattr("app.services.work_item_analysis.auto_start.auto_analyze_after_sync", after_sync)
    run = SimpleNamespace(output=None)
    output = await run_scheduled_intake(db, task=task, task_run=run)
    assert calls == [(project_id, "servicenow", admin.id)]
    assert output["auto_analyze"] == {"started": 1, "results": []} and run.output["summary"]["imported"] == 2


def test_mappings_carry_the_source_neutral_names_only():
    states = normalize_workflow_states(None)
    mappings = normalize_workflow_mappings({
        "development": {"source_status": "In Progress", "source_transition": "Start", "sync_back": True},
        "review": {"jira_status": "In Review", "jira_transition": "Review"},
    }, states=states)
    assert (mappings["development"]["source_status"], mappings["development"]["source_transition"]) == (
        "In Progress", "Start")
    assert "jira_status" not in mappings["development"] and "jira_transition" not in mappings["development"]
    assert (mappings["review"]["source_status"], mappings["review"]["source_transition"]) == (None, None), (
        "a source-specific name maps nothing")


def test_the_sync_mode_is_sync_mode_alone():
    assert _normalize_sync_policy({"sync_mode": "execute"}) == {
        "sync_mode": "execute", "conflict_policy": "require_review"}
    assert executes(_normalize_sync_policy({"jira_sync_mode": "execute"})) is False
    assert executes(_normalize_sync_policy(None)) is False
