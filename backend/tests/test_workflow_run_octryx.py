"""octryx-claude follows the run contract: PreToolUse decides by the run's current phase, Stop submits
evidence, and only the server advances."""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest

from app.services.workflow_runs.limits import pause_run
from app.services.workflow_runs.octryx.stop import run_stop
from app.services.workflow_runs.records import active_run_for_session
from app.time_utils import utc_now
from tests.phased_workflow_fixtures import publish_phased
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_octryx_support import (  # noqa: F401
    CONFIRMED,
    ROOT,
    _bound_run,
    _call,
    _decide,
    _fix_definition,
    _hook,
    _server_pipeline,
)

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.mark.asyncio
async def test_a_device_session_follows_its_run_and_the_phase_decides_every_tool(db):
    run, gateway, key, workspace_id = await _bound_run(db)
    assert (await active_run_for_session(db, gateway.id)).id == run.id  # bound through the job's run header
    run.context = {**run.context, "confirmed_test_files": {f"{CONFIRMED}::test_half_up": {
        "file": CONFIRMED, "path": None, "sha256": None, "device": True}}}
    await db.flush()

    async def decided(tool, **tool_input):  # the launcher reports the edited files as existing
        hook = {**_hook(tool, **tool_input), "workflow_run_facts": {"target_exists": True}}
        return await _decide(db, gateway, key, workspace_id, hook)

    edit_test = await decided("Edit", file_path=f"{ROOT}/{CONFIRMED}", old_string="3", new_string="2")
    assert (edit_test["decision"], edit_test["reason"]) == ("deny", "confirmed_test_protected")
    assert edit_test["workflow_run"]["phase"]["protected_files"] == [CONFIRMED]
    assert (await decided("Edit", file_path=f"{ROOT}/pay/totals.py", old_string="a", new_string="b"))[
        "decision"] == "allow"
    assert (await decided("Bash", command="pytest -v"))["decision"] == "allow"  # the phase runs tests
    corrected = await decided("Bash", command="pytest -q")  # names no test: run with -v instead
    assert (corrected["decision"], corrected["reason"], corrected["updated_input"]) == (
        "allow", "allowed_by_default", {"command": "pytest -v"})
    # The default shell runs it: a rewritten confirmed test is caught by
    # the evidence (``confirmed_test_drift``, test_workflow_run_octryx_hardening), not by parsing the command.
    assert (await decided("Bash", command="sed -i s/3/2/ tests/test_totals.py"))["reason"] == "allowed_by_default"
    assert (await decided("Bash", command="gh pr create --fill"))["reason"] == "platform_action_required"
    assert (await decided("Bash", command="curl -s https://api.github.com/repos/o/r"))["reason"] == (
        "platform_action_required")
    assert (await decided("Bash", command="git push origin HEAD"))["reason"] == "push_by_platform"

    await pause_run(db, run, reason="loop_limit", actor_id=None, detail={"edge_id": "loop"})
    paused = await decided("Edit", file_path=f"{ROOT}/pay/totals.py", old_string="a", new_string="b")
    assert (paused["decision"], paused["reason"]) == ("deny", "run_paused")
    assert "is paused" in paused["message"] and paused["workflow_run"]["paused"]["reason"] == "loop_limit"
    assert (await decided("Read", file_path=f"{ROOT}/pay/totals.py"))["decision"] == "allow"


@pytest.mark.asyncio
async def test_a_deliver_phase_cannot_be_published_and_a_pinned_one_runs_nothing(db):
    # No platform agent has the deliver ceiling (push, PR, deploy are platform actions), so a deliver
    # phase is refused at publish; a run pinned to such an older version runs no tool on a device.
    from fastapi import HTTPException

    from app.models.runtime.flow_definition import FlowDefinitionVersion

    deliver = _fix_definition(capability="deliver", protect=False, tools=[
        "read_workspace_file", "edit_workspace_file", "run_test_suite", "bash"])
    with pytest.raises(HTTPException) as refused:
        await publish_phased(db, deliver)
    assert "phase_agent_ceiling" in {error["code"] for error in refused.value.detail["errors"]}
    run, gateway, key, workspace_id = await _bound_run(db, _fix_definition(protect=False, tools=[
        "read_workspace_file", "edit_workspace_file", "run_test_suite"]))
    version = await db.get(FlowDefinitionVersion, run.flow_definition_version_id)
    pinned = copy.deepcopy(version.definition_json)
    pinned["nodes"][1]["config"]["workflow_contract"]["capability_class"] = "deliver"
    version.definition_json = pinned
    await db.flush()
    denied = await _decide(db, gateway, key, workspace_id, _hook("Bash", command="make build"))
    assert (denied["decision"], denied["reason"]) == ("deny", "phase_agent_unavailable")


@pytest.mark.asyncio
async def test_stop_submits_evidence_and_only_the_server_advances(db):
    run, gateway, key, workspace_id = await _bound_run(db)
    blocked = await run_stop(db, session=gateway, hook_input={}, tool_calls=[], test_prefixes=(("pytest",),))
    assert blocked["state"] == "blocked" and "The test suite ran" in blocked["detail"]
    assert run.current_node_id == "fix"  # the agent's stop never moves the run

    later = utc_now() + timedelta(seconds=5)
    rows = [_call(gateway, "Edit", at=later, file_path=f"{ROOT}/pay/totals.py"),
            _call(gateway, "Bash", at=later + timedelta(seconds=1), command="pytest -q",
                  excerpt="tests/test_zero.py::test_zero PASSED")]
    passed = await run_stop(db, session=gateway, hook_input={}, tool_calls=rows, test_prefixes=(("pytest",),))
    assert passed["state"] == "passed"
    # The phase passed; the green gate (no confirmed red) failed and looped back: the server's decision.
    assert run.gate_results["green"]["state"] == "failed" and run.loop_counters["loop"]["used"] == 1
    assert passed["workflow_run"]["loop"][0]["iteration"] == 2


@pytest.mark.asyncio
async def test_a_phase_that_stops_twice_on_the_same_checks_with_nothing_done_pauses(db):
    run, gateway, key, workspace_id = await _bound_run(db)
    first = await run_stop(db, session=gateway, hook_input={}, tool_calls=[], test_prefixes=(("pytest",),))
    assert first["state"] == "blocked"
    again = await run_stop(db, session=gateway, hook_input={}, tool_calls=[], test_prefixes=(("pytest",),))
    assert again["state"] == "not_applicable" and run.status == "paused"
    assert run.pause_reason == "phase_stalled"


@pytest.mark.asyncio
async def test_a_phase_that_did_something_between_two_stops_is_blocked_again(db):
    run, gateway, key, workspace_id = await _bound_run(db)
    assert (await run_stop(db, session=gateway, hook_input={}, tool_calls=[],
                           test_prefixes=(("pytest",),)))["state"] == "blocked"
    later = utc_now() + timedelta(seconds=5)
    edit = [_call(gateway, "Edit", at=later, file_path=f"{ROOT}/pay/totals.py")]
    again = await run_stop(db, session=gateway, hook_input={}, tool_calls=edit, test_prefixes=(("pytest",),))
    assert again["state"] == "blocked" and run.status == "running"
