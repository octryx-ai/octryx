"""Before a pipeline the stop asks for the full suite; flaky tests, reruns that stay red and the declared browser on the device."""

from __future__ import annotations

import pytest

from app.services.workflow_runs import pipeline, pipeline_failure, pipeline_report
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_pipeline_support import COMMANDS, _at_pipeline, _device_run, _fix_with_pipeline, _report

pytestmark = pytest.mark.usefixtures("scripted_pool")

FLAKY = "tests/system/test_cli.py::test_port_in_use_exits_3"


def _flaky_report(run):
    report = _report(run, [0, 1])
    report["results"][1].update(rerun={"exit_code": 0, "seconds": 1.0, "output_tail": "1 passed", "junit_xml": None,
                                       "tests": [FLAKY]}, flaky=[FLAKY])
    return report


@pytest.mark.asyncio
async def test_before_a_pipeline_the_stop_wants_the_full_suite_but_not_the_proofs_in_the_diff(db, monkeypatch):
    # Without a full run the pass would end on single files and the pipeline would loop red.
    from datetime import timedelta

    from app.models import ToolCall
    from app.services.workflow_runs.octryx.stop import run_stop
    from app.time_utils import utc_now
    from tests.workflow_run_octryx_support import ROOT, _fix_definition

    async def no_turn(_db, _run, _node):
        return None

    async def device(_db, _run):
        return "device"

    async def commands(_db, _run):
        return list(COMMANDS), [], COMMANDS[-1] if len(COMMANDS) > 1 else ""

    monkeypatch.setattr(pipeline, "commands_for", commands)
    monkeypatch.setattr("app.services.workflow_runs.workspace.preparation.runtime_of", device)
    monkeypatch.setattr("app.services.workflow_runs.octryx.continuation.runtime_step_entered", no_turn)

    def rows(gateway):
        return [ToolCall(session_id=gateway.id, tool_name="Edit", status="success", created_at=utc_now() + timedelta(
            seconds=5), parameters={"source": "gateway", "file_path": f"{ROOT}/pay/totals.py"},
            result={"is_error": False})]

    change = {"workflow_run_facts": {"change": {"base": "a" * 40, "patch": "diff --git a/pay/totals.py b/pay/totals.py\n"
                                                                           "+x = 1\n"}}}
    run, gateway, _key, _workspace = await _device_run(db, _fix_with_pipeline(), monkeypatch)
    blocked = await run_stop(db, session=gateway, hook_input=change, tool_calls=rows(gateway),
                             test_prefixes=(("pytest",),))
    assert blocked["state"] == "blocked" and "full test suite" in blocked["detail"]
    assert "Task list" not in blocked["detail"]  # the proofs stay the pipeline's
    full = ToolCall(session_id=gateway.id, tool_name="Bash", status="success",
                    created_at=utc_now() + timedelta(seconds=9),
                    parameters={"input": {"command": f"{COMMANDS[0]} 2>&1 | tail -20"}},
                    result={"is_error": False, "excerpt": "........\n8 passed in 0.4s"})
    answer = await run_stop(db, session=gateway, hook_input=change, tool_calls=[*rows(gateway), full],
                            test_prefixes=(("pytest",),))
    assert answer["state"] == "passed" and run.current_node_id == "pipeline"
    assert [task["status"] for task in run.context["task_list"]] == ["open", "open"]  # the pipeline proves them

    run, gateway, _key, _workspace = await _device_run(db, _fix_definition(protect=False), monkeypatch)
    blocked = await run_stop(db, session=gateway, hook_input=change, tool_calls=rows(gateway),
                             test_prefixes=(("pytest",),))
    assert blocked["state"] == "blocked" and "Task list: no proof test in the change for T1" in blocked["detail"]
    assert "pipeline_after" not in blocked["workflow_run"]["phase"]


@pytest.mark.asyncio
async def test_before_a_pipeline_pytest_q_is_fine_elsewhere_it_is_asked_again_with_v(db, monkeypatch):
    from tests.workflow_run_octryx_support import _decide, _fix_definition, _hook

    run, gateway, key, workspace_id = await _device_run(db, _fix_with_pipeline(), monkeypatch)
    assert (await _decide(db, gateway, key, workspace_id, _hook("Bash", command="pytest -q tests/test_x.py")))[
        "decision"] == "allow"
    run, gateway, key, workspace_id = await _device_run(db, _fix_definition(protect=False), monkeypatch)
    corrected = await _decide(db, gateway, key, workspace_id, _hook("Bash", command="pytest -q tests/test_x.py"))
    assert corrected["updated_input"] == {"command": "pytest -v tests/test_x.py"}  # run with -v
    from tests.workflow_run_octryx_support import STRICT, set_tool_defaults

    await set_tool_defaults(db, workspace_id, **STRICT)
    assert (await _decide(db, gateway, key, workspace_id, _hook("Bash", command="pytest -q tests/test_x.py")))[
        "decision"] == "deny"


@pytest.mark.asyncio
async def test_a_test_that_fails_then_passes_on_the_rerun_is_flaky_and_not_counted_the_first_time(db, monkeypatch):
    from sqlalchemy import select

    from app.models import WorkflowRunEvent

    run, session = await _at_pipeline(db, monkeypatch)
    assert await pipeline_report.record_report(db, run, _flaky_report(run), session_id=session.id) == "green"
    assert run.status == "completed"
    assert run.context["pipeline"]["flaky"] == [FLAKY] and run.context["pipeline_flaky"] == {FLAKY: 1}
    assert run.context["pipeline"]["results"][1]["rerun"]["exit_code"] == 0  # the report keeps the re-run
    events = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id))).scalars().all()
    reported = [event.detail for event in events if event.kind == pipeline.EVENT_REPORTED][-1]
    assert reported["flaky"] == [FLAKY] and reported["commands"][1]["rerun_tests"] == [FLAKY]
    reasons = [str((event.detail or {}).get("reason") or "") for event in events]
    assert any("flaky, not counted this time" in reason and FLAKY in reason for reason in reasons)


@pytest.mark.asyncio
async def test_the_same_test_flaky_again_in_the_run_counts_as_red_and_the_agent_is_told(db, monkeypatch):
    run, session = await _at_pipeline(db, monkeypatch)
    run.context = {**run.context, "pipeline_flaky": {FLAKY: 1}}  # flaky once already in an earlier pass
    assert await pipeline_report.record_report(db, run, _flaky_report(run), session_id=session.id) == "red"
    red = pipeline_failure.failure_for_agent(run)
    assert red["flaky_again"] == [FLAKY] and "deterministic" in red["flaky_rule"]
    assert run.context["pipeline_flaky"] == {FLAKY: 2}


@pytest.mark.asyncio
async def test_a_rerun_that_stays_red_keeps_the_pipeline_red(db, monkeypatch):
    run, session = await _at_pipeline(db, monkeypatch)
    report = _report(run, [0, 1])
    report["results"][1].update(rerun={"exit_code": 1, "seconds": 1.0, "output_tail": "1 failed", "junit_xml": None,
                                       "tests": [FLAKY]}, flaky=[])
    assert await pipeline_report.record_report(db, run, report, session_id=session.id) == "red"
    assert "pipeline_flaky" not in run.context


@pytest.mark.asyncio
async def test_the_declared_browser_reaches_the_device(db, monkeypatch):
    async def bundled(_db, _run):
        return "chromium"

    monkeypatch.setattr(pipeline, "browser_for", bundled)
    run, _session = await _at_pipeline(db, monkeypatch)
    assert pipeline.contract_view(run)["browser"] == "chromium"
