"""Teamwork, the ``parallel_work`` node: publish validation, and the scheduler with a fake executor.

The coordinator's plan runs as one session per item; items whose dependencies are merged start (waves), each done item
is merged at once, all merged routes ``done``; a failed, blocked or conflicting item that leaves nothing to run routes
``replan`` back to the coordinator with one finding per item. The run's task list is one task per item. An item's turn
goes through the real turn-end checks under its own synthetic phase and reports only to its item.
"""

from __future__ import annotations

import uuid

import pytest

from app.models import Session
from app.services.workflow_runs import teamwork
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.phase_contract import phase_definition
from app.services.workflow_runs.phase_outputs import submit_output
from app.services.workflow_runs.teamwork import item_results
from app.services.workflow_runs.views import run_view
from tests.phased_workflow_fixtures import admin_user, phase_turn
from tests.teamwork_engine_support import fake, finish_item, item, items_of, planned_run, team_definition  # noqa: F401


async def _graph(db, run):
    from app.services.workflow_runs.graph import graph_for_run

    return await graph_for_run(db, run)


@pytest.mark.asyncio
async def test_items_run_in_waves_merge_at_once_and_the_node_is_done(db, fake):  # noqa: F811
    run, _session = await planned_run(db, [item("api"), item("ui", role="frontend"),
                                           item("e2e", depends_on=["api", "ui"])], copy_dir=fake.copy)
    assert run.current_node_id == "work" and run.status == "running"
    assert [key for key, _ in fake.started] == ["api", "ui"]  # e2e waits for both
    tasks = run.context["task_list"]
    assert [(task["id"], task["roles"], task["proofs"]) for task in tasks] == [
        ("api", ["backend"], ["tests/test_api.py::test_api"]), ("ui", ["frontend"], ["tests/test_ui.py::test_ui"]),
        ("e2e", ["backend"], ["tests/test_e2e.py::test_e2e"])]
    assert teamwork.work_of(run)["contract"] == "GET /api/search"

    resolution = await finish_item(db, run, "api")
    facts = resolution["workflow_contract"]["workflow_run_phase"]
    assert facts["work_item"]["paths"] == ["api/**", "tests/test_api.py"] and facts["shared_contract"] == "GET /api/search"
    assert [task["id"] for task in facts["task_list"]] == ["api"]  # its own proof, not the story's list
    assert resolution["workflow_contract"]["path_rules"]["write"] == ["api/**", "tests/test_api.py"]
    assert items_of(run)["api"]["status"] == "merged" and items_of(run)["e2e"]["status"] == "pending"
    assert run.current_node_id == "work"

    await finish_item(db, run, "ui")
    assert [key for key, _ in fake.started] == ["api", "ui", "e2e"]  # the next wave once both are merged
    await finish_item(db, run, "e2e")
    assert (run.status, run.outcome, run.context["results"]["work"]) == ("completed", "done", "done")
    assert fake.finished == 1
    view = (await run_view(db, run, access="write", user=await admin_user(db)))["work"]
    assert [entry["id"] for entry in view["items"]] == ["api", "ui", "e2e"]
    assert view["items"][2]["depends_on"] == ["api", "ui"] and view["route"] == "done"


@pytest.mark.asyncio
async def test_a_blocked_item_replans_with_findings_and_the_revision_resumes_it(db, fake):  # noqa: F811
    run, session = await planned_run(db, [item("api"), item("ui", role="frontend"),
                                          item("e2e", depends_on=["api", "ui"])], copy_dir=fake.copy)
    await finish_item(db, run, "api", value="blocked", tools=())  # it needs a decision: no waiting, blocked
    assert items_of(run)["api"]["status"] == "blocked" and run.current_node_id == "work"  # ui still running
    await finish_item(db, run, "ui")
    assert run.current_node_id == "plan"  # nothing left to run: back to the coordinator
    assert run.loop_counters["replan"]["used"] == 1
    findings = phase_definition(run, (await _graph(db, run)).nodes["plan"])["workflow_contract"][
        "workflow_run_phase"]["findings"]
    assert any(line.startswith("item api (backend, blocked") and "api blocked" in line for line in findings)
    assert any(line.startswith("item e2e") and "waits for api" in line for line in findings)

    first_session = items_of(run)["api"]["session_id"]
    resolution = await run_turn_resolution(db, session, user_message="Re-plan.")
    await submit_output(db, run, "submit_work_plan", {"contract": "v2", "items": [
        item("api", instructions="Build api; the PO chose offset paging."), item("ui", role="frontend"),
        item("e2e", depends_on=["api", "ui"])]}, session_id=session.id)
    await phase_turn(db, session.id, resolution, ["submit_work_plan"])
    assert run.current_node_id == "work"
    api = items_of(run)["api"]
    assert (api["status"], api["iteration"]) == ("running", 2)
    assert fake.started[-1] == ("api", first_session)  # it resumes its own session
    assert items_of(run)["ui"]["status"] == "merged"  # merged work stays merged


@pytest.mark.asyncio
async def test_a_failed_turn_and_a_merge_conflict_route_replan(db, fake):  # noqa: F811
    fake.conflicts = {"ui"}
    run, _session = await planned_run(db, [item("api"), item("ui", role="frontend")], copy_dir=fake.copy)
    await finish_item(db, run, "api", tools=())  # its checks did not pass (no file written)
    assert items_of(run)["api"]["status"] == "failed"
    await finish_item(db, run, "ui")
    assert items_of(run)["ui"]["status"] == "conflict" and items_of(run)["ui"]["conflicts"] == ["ui/shared.ts"]
    assert run.current_node_id == "plan" and run.context["results"]["work"] == "replan"
    lines = run.gate_results["work"]["results"]
    assert [line["description"].split(" (")[0] for line in lines] == ["item api", "item ui"]
    assert "conflicts in ui/shared.ts" in lines[1]["description"]


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
async def test_parallel_false_and_the_capacity_run_one_at_a_time(db, fake):  # noqa: F811
    run, _session = await planned_run(db, [item("api"), item("ui", role="frontend")],
                                      definition=team_definition(parallel=False), copy_dir=fake.copy)
    assert [key for key, _ in fake.started] == ["api"]
    await finish_item(db, run, "api")
    assert [key for key, _ in fake.started] == ["api", "ui"]


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
    """A device item's Stop arrives with its Claude Code gateway session (bound as ``octryx:<key>``, carrying a
    copy of the item marker), not the item's chat thread; it is the item's own report, a stale iteration's is not."""
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
