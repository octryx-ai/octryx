"""A phase node may let its device turn start Claude Code's own sub-agents (``config.subagents: true``, default off)."""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import select

from app.models import DeviceJob
from app.services.devices.jobs import start_turn
from app.services.devices.jobs_channel import DeviceJobHandlers
from app.services.workflow_runs.records import new_chat_session, start_run
from tests.devices.device_support import RecordingConnection, device_with_grant
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.phased_workflow_fixtures import admin_user, publish_phased
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_octryx_support import CONFIRMED, ROOT, _bound_run, _decide, _fix_definition, _hook

pytestmark = pytest.mark.usefixtures("scripted_pool")

FOLDER = "/home/sample/src"


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)


def _flagged(definition: dict) -> dict:
    flagged = copy.deepcopy(definition)
    next(node for node in flagged["nodes"] if node["id"] == "fix")["config"]["subagents"] = True
    return flagged


async def _offer_at_phase(db, definition: dict) -> dict:
    workspace_id = await seed_workspace(db)
    admin = await admin_user(db)
    thread = await new_chat_session(db, admin, workspace_id)
    device, _ = await device_with_grant(db, admin, folders=[FOLDER])
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition),
                          project_id=workspace_id, session=thread,
                          runtime_target={"kind": "device", "device_id": device.id, "folder": FOLDER,
                                          "profile": "governed"})
    assert run.current_node_id == "fix"
    for job in (await db.execute(select(DeviceJob).where(DeviceJob.session_id == thread.id))).scalars():
        job.status = "idle"  # the run's own offer: this test offers the phase turn itself
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
    edit_test = await decided("Edit", agent_id="a1", file_path=f"{ROOT}/{CONFIRMED}", old_string="3", new_string="2")
    assert (edit_test["decision"], edit_test["reason"]) == ("deny", "confirmed_test_protected")
    assert (await decided("Edit", agent_id="a1", file_path=f"{ROOT}/pay/totals.py", old_string="a",
                          new_string="b"))["decision"] == "allow"
    assert (await decided("Bash", agent_id="a1", command="git push origin HEAD"))["reason"] == "push_by_platform"


@pytest.mark.asyncio
async def test_an_unflagged_phase_judges_an_agent_call_like_any_tool_call(db):
    _run, gateway, key, workspace_id = await _bound_run(db, _fix_definition())
    hook = _hook("Agent", description="Find callers", prompt="Find the callers", subagent_type="Explore")
    assert (await _decide(db, gateway, key, workspace_id, hook))["decision"] == "allow"


@pytest.mark.asyncio
async def test_a_flagged_phase_records_a_sub_agents_missed_checks_without_blocking_it(db):
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
    assert main["state"] == "blocked" and "The test suite ran" in main["detail"]
