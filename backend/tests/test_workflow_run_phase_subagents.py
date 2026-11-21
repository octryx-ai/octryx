"""A phase node may let its device turn start Claude Code's own sub-agents (``config.subagents: true``, default off).

- the job offer of a run at a flagged phase carries ``subagents: true``; at an unflagged phase, or without a run, the
  offer has no such key (the launcher then keeps the six lean tools);
- the PreToolUse decision allows the ``Agent`` call (or its alias ``Task``) in a flagged phase, exactly as
  it already did in any phase (it starts nothing outside the phase), and a sub-agent's own tool calls are judged by
  the same phase rules as the main session's: a confirmed test stays protected whoever edits it.
"""

from __future__ import annotations

import copy

import pytest

from app.services.devices.jobs import start_turn
from app.services.devices.jobs_channel import DeviceJobHandlers
from app.services.workflow_runs.records import new_chat_session, start_run
from tests.devices.device_support import RecordingConnection, device_with_grant
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.phased_workflow_fixtures import admin_user, publish_phased
from tests.workflow_run_octryx_support import CONFIRMED, ROOT, _bound_run, _decide, _fix_definition, _hook

FOLDER = "/home/sample/src"


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    """The fix phase runs tests: the server build lock is lifted as in ``test_workflow_run_octryx``."""
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)


def _flagged(definition: dict) -> dict:
    flagged = copy.deepcopy(definition)
    next(node for node in flagged["nodes"] if node["id"] == "fix")["config"]["subagents"] = True
    return flagged


async def _offer_at_phase(db, definition: dict) -> dict:
    """The job offer a device gets for a turn on the chat thread of a run that stands at its ``fix`` phase."""
    workspace_id = await seed_workspace(db)
    admin = await admin_user(db)
    thread = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition),
                          project_id=workspace_id, session=thread)
    assert run.current_node_id == "fix"
    device, _ = await device_with_grant(db, admin, folders=[FOLDER])
    await start_turn(db, owner_user_id=admin.id, device=device, session_id=thread.id, workspace_id=workspace_id,
                     folder=FOLDER, profile="governed", prompt="Work the phase")
    connection = RecordingConnection(device.id)
    await DeviceJobHandlers().tick(db, connection)
    [offer] = [body for kind, body in connection.sent if kind == "job_offer"]
    assert offer["workflow_run_id"] == run.id
    return offer


@pytest.mark.asyncio
async def test_the_offer_carries_subagents_only_for_a_flagged_phase(db):
    assert (await _offer_at_phase(db, _flagged(_fix_definition())))["subagents"] is True
    assert "subagents" not in await _offer_at_phase(db, _fix_definition())


@pytest.mark.asyncio
async def test_an_agent_call_passes_a_flagged_phase_and_its_sub_agents_tools_follow_the_phase_rules(db):
    run, gateway, key, workspace_id = await _bound_run(db, _flagged(_fix_definition()))
    run.context = {**run.context, "confirmed_test_files": {f"{CONFIRMED}::test_half_up": {
        "file": CONFIRMED, "path": None, "sha256": None, "device": True}}}
    await db.flush()

    async def decided(tool, agent_id: str = "", **tool_input):
        hook = {**_hook(tool, **tool_input), "workflow_run_facts": {"target_exists": True},
                **({"agent_id": agent_id, "agent_type": "general-purpose"} if agent_id else {})}
        return await _decide(db, gateway, key, workspace_id, hook)

    for name in ("Agent", "Task"):
        assert (await decided(name, description="Find callers", prompt="Find the callers of totals",
                              subagent_type="Explore"))["decision"] == "allow", name
    # Inside the sub-agent: the same phase decides, the confirmed test stays protected, the shell rules hold.
    edit_test = await decided("Edit", agent_id="a1", file_path=f"{ROOT}/{CONFIRMED}", old_string="3", new_string="2")
    assert (edit_test["decision"], edit_test["reason"]) == ("deny", "confirmed_test_protected")
    assert (await decided("Edit", agent_id="a1", file_path=f"{ROOT}/pay/totals.py", old_string="a",
                          new_string="b"))["decision"] == "allow"
    assert (await decided("Bash", agent_id="a1", command="git push origin HEAD"))["reason"] == "push_by_platform"


@pytest.mark.asyncio
async def test_an_unflagged_phase_judges_an_agent_call_like_any_tool_call(db):
    # The launcher offers no Agent tool there, and a call that still arrives (an interactive session bound to the
    # run) is judged like any tool call of the phase.
    _run, gateway, key, workspace_id = await _bound_run(db, _fix_definition())
    hook = _hook("Agent", description="Find callers", prompt="Find the callers", subagent_type="Explore")
    assert (await _decide(db, gateway, key, workspace_id, hook))["decision"] == "allow"


@pytest.mark.asyncio
async def test_a_flagged_phase_records_a_sub_agents_missed_checks_without_blocking_it(db):
    """Claude Code 2.1.318: an Explore sub-agent that only reads misses the implement phase's test checks; in an
    unflagged phase its SubagentStop is blocked (S6, unchanged), in a flagged one it is recorded and ends: the main
    session hands it a part, and the main Stop judges the phase."""
    from datetime import timedelta

    from app.services.workflow_runs.octryx.stop import run_stop
    from app.time_utils import utc_now
    from tests.workflow_run_octryx_support import _call

    child = {"hook_event_name": "SubagentStop", "agent_id": "agent-7", "agent_type": "Explore"}
    for definition, state in ((_fix_definition(), "blocked"), (_flagged(_fix_definition()), "passed")):
        run, gateway, _key, _workspace_id = await _bound_run(db, definition)
        rows = [_call(gateway, "Read", at=utc_now() + timedelta(seconds=5), file_path=f"{ROOT}/pay/totals.py",
                      agent_id="agent-7")]
        answer = await run_stop(db, session=gateway, hook_input=child, tool_calls=rows, test_prefixes=(("pytest",),))
        assert answer["state"] == state and run.current_node_id == "fix"
        assert run.context["octryx_children"]["agent-7"]["state"] == "failed"
        assert "The test suite ran" in run.context["octryx_children"]["agent-7"]["missed_checks"]
    main = await run_stop(db, session=gateway, hook_input={"hook_event_name": "Stop"}, tool_calls=rows,
                          test_prefixes=(("pytest",),))
    assert main["state"] == "blocked" and "The test suite ran" in main["detail"]  # the phase is still judged
