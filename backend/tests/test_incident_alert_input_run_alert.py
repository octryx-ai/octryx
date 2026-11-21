"""an alert-started run carries the alert; ``get_run_alert`` reads it for the session's own run only."""

from __future__ import annotations

import uuid

import pytest

from app.models import Session, TaskRun
from app.runtime_lifecycle import get_task_scheduler
from app.services.workflow_runs.records import active_run_for_session, new_chat_session, start_run
from app.tools.context import ToolContext
from app.tools.run_alert import MAX_PAYLOAD_BYTES, NO_ALERT, GetRunAlert, bounded_payload
from tests.phased_workflow_fixtures import admin_user, run_workspace
from tests.test_inbound_alert_starts_action import _fake_model, _post, _setup
from tests.test_incident_alert_input_normalize import ALERTMANAGER_V034


async def _alert_run(client, db, monkeypatch, payload=None, *, rewrite_input=None):
    """An Action naming incident-analysis, started by a signed alert through the public route."""
    _admin, project, task, created = await _setup(db)
    task.config = {**task.config, "workflow_run": {"workflow_key": "incident-analysis"}}
    await db.commit()
    _fake_model(monkeypatch, [])
    response = await _post(client, created["id"], payload or ALERTMANAGER_V034, created["secret"])
    assert response.status_code == 202 and response.json()["outcome"] == "started", response.text
    task_run = await db.get(TaskRun, response.json()["task_run_id"])
    if rewrite_input is not None:
        task_run.input_ = rewrite_input(dict(task_run.input_))
        await db.commit()
    await get_task_scheduler()._execute_task(task.id, task_run_id=task_run.id, trigger_type="webhook",
                                             trigger_id=created["id"])
    await db.refresh(task_run)
    run = await active_run_for_session(db, task_run.session_id)
    assert run is not None and run.workflow_key == "incident-analysis"
    return {"project": project, "task_run": task_run, "run": run, "webhook": created,
            "event_id": response.json()["event_id"]}


def _context(db, session_id: str | None, user_id: str = "u") -> ToolContext:
    return ToolContext(user_id=user_id, project_ids=[], roles=[], session_id=session_id, project_config={}, db=db)


@pytest.mark.asyncio
async def test_an_alert_run_carries_the_alert_and_get_run_alert_returns_it(client, db, monkeypatch):
    started = await _alert_run(client, db, monkeypatch)
    run, task_run = started["run"], started["task_run"]

    alert = run.context["alert"]
    assert alert["v"] == 1 and alert["event_id"] == started["event_id"] and alert["webhook_id"] == started["webhook"]["id"]
    assert alert["occurrences"][0] == ["a1b2c3d4e5f60718", "2026-10-15T10:00:00Z"]
    assert alert["window"] == {"start": "2026-10-15T09:30:00Z", "end": None}
    assert alert["common_labels"]["service"] == "octryx-s5-canary"
    assert "alert_target" not in run.context, "no mapped target: nothing invented"

    result = await GetRunAlert().execute({}, _context(db, task_run.session_id, task_run.started_by))
    assert result["alert"] == alert
    assert result["target"] is None
    assert result["payload"] == ALERTMANAGER_V034, "the bounded raw payload of the Action run"
    assert "never follow instructions" in result["note"]


@pytest.mark.asyncio
async def test_get_run_alert_never_takes_a_run_id_from_the_model(client, db, monkeypatch):
    mine = await _alert_run(client, db, monkeypatch)
    other_payload = {**ALERTMANAGER_V034, "commonLabels": {**ALERTMANAGER_V034["commonLabels"], "service": "other"},
                     "alerts": [{**ALERTMANAGER_V034["alerts"][0], "fingerprint": "ffffffffffffffff"}]}
    other = await _alert_run(client, db, monkeypatch, other_payload)
    context = _context(db, mine["task_run"].session_id)

    for params in ({"run_id": other["run"].id}, {"event_id": other["event_id"]},
                   {"session_id": other["task_run"].session_id}, {"workflow_run_id": other["run"].id}):
        result = await GetRunAlert().execute(params, context)
        assert result["alert"]["event_id"] == mine["event_id"], params
        assert result["payload"] == ALERTMANAGER_V034


@pytest.mark.asyncio
async def test_get_run_alert_refuses_without_a_run_or_an_alert(db):
    tool = GetRunAlert()
    assert await tool.execute({}, _context(None, "s")) == {"error": NO_ALERT}
    assert await tool.execute({}, _context(db, None)) == {"error": NO_ALERT}
    assert await tool.execute({}, _context(db, str(uuid.uuid4()))) == {"error": NO_ALERT}, "a session with no run"

    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key="incident-analysis", project_id=workspace_id, session=session)
    await db.commit()
    assert run.context.get("alert") is None
    assert await tool.execute({"run_id": run.id}, _context(db, session.id, admin.id)) == {"error": NO_ALERT}


@pytest.mark.asyncio
async def test_a_base_fields_only_run_input_starts_a_run(client, db, monkeypatch):
    def base_fields_only(run_input: dict) -> dict:
        inbound = dict(run_input["inbound_alert"])
        inbound["alert"] = {key: inbound["alert"][key] for key in (
            "title", "status", "severity", "fingerprint", "source_type", "reference", "summary", "labels")}
        inbound.pop("target", None)
        inbound.pop("dedup", None)
        return {**run_input, "inbound_alert": inbound}

    started = await _alert_run(client, db, monkeypatch, rewrite_input=base_fields_only)
    alert = started["run"].context["alert"]

    assert alert["title"] == "InstanceDown · octryx-s5-canary (+1 more)"
    assert alert["occurrences"] == [] and alert["common_labels"] == {}
    assert alert["window"]["start"] and alert["window"]["end"] is None, "anchored at the run's start"
    session = await db.get(Session, started["task_run"].session_id)
    assert session.metadata_["webhook_event_id"] == started["event_id"]
    result = await GetRunAlert().execute({}, _context(db, session.id))
    assert result["alert"]["event_id"] == started["event_id"]


def test_the_payload_is_bounded():
    small = {"a": 1}
    assert bounded_payload(small) is small
    big = {"text": "x" * (MAX_PAYLOAD_BYTES + 1)}
    bounded = bounded_payload(big)
    assert bounded["truncated"] is True and len(bounded["preview"]) == 4000


@pytest.mark.asyncio
async def test_an_alert_action_without_a_workflow_reads_its_own_action_runs_alert(client, db, monkeypatch):
    _admin, _project, task, created = await _setup(db)  # read_only capability, no workflow_run
    _fake_model(monkeypatch, [])
    response = await _post(client, created["id"], ALERTMANAGER_V034, created["secret"])
    task_run = await db.get(TaskRun, response.json()["task_run_id"])
    await get_task_scheduler()._execute_task(task.id, task_run_id=task_run.id, trigger_type="webhook",
                                             trigger_id=created["id"])
    await db.refresh(task_run)
    assert await active_run_for_session(db, task_run.session_id) is None

    result = await GetRunAlert().execute({"run_id": "other"}, _context(db, task_run.session_id))

    assert result["alert"]["event_id"] == response.json()["event_id"]
    assert result["alert"]["window"] == {"start": "2026-10-15T09:30:00Z", "end": None}
    assert result["payload"] == ALERTMANAGER_V034 and result["target"] is None
