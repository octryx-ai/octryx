"""``GET /workflow-runs?view=work`` and ``GET /workflow-runs/{id}/screens`` stay fast with big runs. The list never
reads the runs' big JSON, asks a fixed number of queries whatever the number of runs, and pages by cursor; the
screenshot folder is read off the event loop within a few seconds."""

from __future__ import annotations

import asyncio
import re
import time

import pytest
from sqlalchemy import event

from app.models import User
from app.services.workflow_runs.records import new_chat_session, start_run
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.phased_workflow_fixtures import publish_phased
from tests.policy_engine_support import bearer
from tests.test_workflow_runs_work_view import DEFINITION

pytestmark = pytest.mark.asyncio

BIG_PATCH = "+" + "x" * 2_000_000  # a device change's patch, as live runs carry them (megabytes)


async def _runs(db, count: int):
    workspace_id = await seed_workspace(db)
    person = await db.get(User, await seed_member(db, workspace_id=workspace_id, role="member"))
    key = await publish_phased(db, DEFINITION)
    for _ in range(count):
        run = await start_run(db, user=person, workflow_key=key, project_id=workspace_id,
                              session=await new_chat_session(db, person, workspace_id))
        run.context = {**dict(run.context or {}), "device_change": {"patch": BIG_PATCH},
                       "stop": {"reason": "kept for the row"}}
        run.gate_results = {"green": {"results": [{"detail": "y" * 200_000}]}}
    await db.commit()
    return workspace_id, person


def _counting(db) -> list[str]:
    statements: list[str] = []
    engine = db.get_bind().sync_engine if hasattr(db.get_bind(), "sync_engine") else db.get_bind()
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(str(args[2])))
    return statements


async def test_the_work_list_reads_no_big_json_and_a_fixed_number_of_queries(client, db):
    workspace_id, person = await _runs(db, 12)
    statements = _counting(db)
    started = time.perf_counter()
    answer = await client.get(f"/api/v1/workflow-runs?project_id={workspace_id}&view=work", headers=bearer(person.id))
    took = time.perf_counter() - started
    assert answer.status_code == 200, answer.text
    rows = answer.json()["runs"]
    assert len(rows) == 12 and all(row["stop_reason"] == "kept for the row" for row in rows)
    assert len(answer.content) < 200_000  # nothing of the 2 MB patches or the gate details reaches the list
    listed = [text for text in statements if "FROM workflow_runs" in text and "workflow_runs.title" in text]
    # Only the two context parts, through the database's JSON path: never the whole column.
    whole = [re.sub(r"JSON\w*\(\s*workflow_runs\.context|workflow_runs\.context\s*->", "", text) for text in listed]
    assert listed and all("workflow_runs.context" not in text and "workflow_runs.gate_results" not in text
                          for text in whole), listed[0][:600]
    assert len(statements) <= 25, len(statements)  # not two more per run (12 runs)
    assert took < 5, took


async def test_the_list_pages_by_cursor(client, db):
    workspace_id, person = await _runs(db, 3)
    first = (await client.get(f"/api/v1/workflow-runs?project_id={workspace_id}&limit=2",
                              headers=bearer(person.id))).json()
    assert len(first["runs"]) == 2 and first["next_before"]
    rest = (await client.get(f"/api/v1/workflow-runs?project_id={workspace_id}&limit=2&before={first['next_before']}",
                             headers=bearer(person.id))).json()
    seen = {row["id"] for row in first["runs"]}
    assert rest["runs"] and not seen & {row["id"] for row in rest["runs"]} and rest["next_before"] is None


async def test_a_hanging_screenshot_store_answers_in_seconds_with_no_screens(client, db, monkeypatch):
    from app.api.routes import workflow_run_detail as routes
    from app.services.workflow_runs.review import screens

    workspace_id, person = await _runs(db, 1)
    run_id = (await client.get(f"/api/v1/workflow-runs?project_id={workspace_id}",
                               headers=bearer(person.id))).json()["runs"][0]["id"]

    def hanging(_run, _node):
        time.sleep(3)  # a stalled mount: the thread waits, the request does not
        return []

    monkeypatch.setattr(screens, "collect", hanging)
    monkeypatch.setattr(routes, "SCREENS_TIMEOUT", 0.3)
    started = time.perf_counter()
    answer = await client.get(f"/api/v1/workflow-runs/{run_id}/screens", headers=bearer(person.id))
    assert answer.status_code == 200 and answer.json() == {"screens": []}
    assert time.perf_counter() - started < 2
    await asyncio.sleep(0)
