"""Teamwork, the ``parallel_work`` node: publish validation, and the scheduler with a fake executor
(waves, merges, and ``replan`` with one finding per item)."""

from __future__ import annotations

import uuid

import pytest

from app.models import Session
from app.services.workflow_runs import teamwork
from app.services.workflow_runs.phase_outputs import submit_output
from app.services.workflow_runs.teamwork import item_results
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.teamwork_engine_support import fake, finish_item, item, items_of, planned_run, team_definition  # noqa: F401

pytestmark = pytest.mark.usefixtures("scripted_pool")










@pytest.mark.asyncio
async def test_a_transient_failure_retries_once_by_resuming(db, fake):  # noqa: F811
    run, _session = await planned_run(db, [item("api")], copy_dir=fake.copy)
    session_id = items_of(run)["api"]["session_id"]
    await item_results.item_finished(db, run, key="api", session_id=session_id, state="failed", transient=True)
    assert fake.started == [("api", None), ("api", session_id)]
    assert (items_of(run)["api"]["status"], items_of(run)["api"]["attempts"]) == ("running", 2)
    await item_results.item_finished(db, run, key="api", session_id=session_id, state="failed", transient=True)
    assert run.current_node_id == "plan"  # the second failure is the item's: the coordinator decides
    assert run.gate_results["work"]["results"][0]["description"].startswith("item api (backend, failed")




@pytest.mark.asyncio
async def test_the_coordinator_revises_the_plan_while_items_run(db, fake):  # noqa: F811
    run, session = await planned_run(db, [item("api"), item("ui", role="frontend")], copy_dir=fake.copy)
    changed = await submit_output(db, run, "submit_work_plan", {"contract": "", "items": [
        item("api", instructions="different"), item("ui", role="frontend")]}, session_id=session.id)
    assert changed["state"] == "refused" and "api: is running and cannot be changed" in changed["message"]
    overlap = await submit_output(db, run, "submit_work_plan", {"contract": "", "items": [
        item("api"), item("ui", role="frontend"), item("docs", paths=["api/README.md"])]}, session_id=session.id)
    assert overlap["state"] == "refused" and "api and docs can run at the same time" in overlap["message"]
    added = await submit_output(db, run, "submit_work_plan", {"contract": "", "items": [
        item("api"), item("ui", role="frontend"), item("search", paths=["search/**"])]}, session_id=session.id)
    assert added["state"] == "recorded"
    assert [key for key, _ in fake.started] == ["api", "ui", "search"]
    assert [task["id"] for task in run.context["task_list"]] == ["api", "ui", "search"]


@pytest.mark.asyncio
async def test_an_item_records_only_its_own_result(db, fake):  # noqa: F811
    run, _session = await planned_run(db, [item("api"), item("ui", role="frontend")], copy_dir=fake.copy)
    api_session = items_of(run)["api"]["session_id"]
    refused = await submit_output(db, run, "submit_work_plan", {"contract": "", "items": [item("x")]},
                                  session_id=api_session)
    assert refused["state"] == "refused"
    wrong = await submit_output(db, run, "submit_phase_result", {"value": "maybe"}, session_id=api_session)
    assert wrong["state"] == "refused" and "done, blocked" in wrong["message"]
    await submit_output(db, run, "submit_phase_result", {"value": "done"}, session_id=api_session)
    assert items_of(run)["api"]["result"]["value"] == "done" and items_of(run)["ui"]["result"] is None
    assert "result" not in dict(run.context.get("outputs") or {})  # never the run's single result slot


@pytest.mark.asyncio
async def test_a_device_items_gateway_session_reports_for_its_item(db, fake):  # noqa: F811
    run, _session = await planned_run(db, [item("api")], copy_dir=fake.copy)

    async def gateway(iteration: int) -> Session:
        session = Session(id=str(uuid.uuid4()), user_id=run.requested_by, project_id=run.project_id,
                          agent_type="coding", status="active", metadata_={teamwork.ITEM_METADATA_KEY: {
                              "run_id": run.id, "key": "api", "iteration": iteration}})
        db.add(session)
        await db.flush()
        return session

    stale = await gateway(0)
    await item_results.item_finished(db, run, key="api", session_id=stale.id, state="passed")
    assert items_of(run)["api"]["status"] == "running"
    current = await gateway(1)
    assert (await submit_output(db, run, "submit_phase_result", {"value": "done"},
                                session_id=current.id))["state"] == "recorded"
    await item_results.item_finished(db, run, key="api", session_id=current.id, state="passed")
    assert items_of(run)["api"]["status"] == "merged" and run.status == "completed"
