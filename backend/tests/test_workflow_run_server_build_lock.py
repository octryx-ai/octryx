"""A run that builds or tests the repository never runs on the server.

- a server target (or none: the server) for a workflow that declares a test/lint step is refused at start with
  ``server_build_not_allowed`` and the plain message; nothing is written;
- the same workflow on the owner's device or an octryx-claude terminal starts;
- a read-only workflow (no test/lint step) still starts on the server;
- switching a running device run to the server is refused, the run stays where it was and the refusal is a run
  event (``server_build_refused``) with the reason.
"""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import func, select

from app.models import WorkflowRun, WorkflowRunEvent
from app.services.workflow_runs.records import WorkflowRunError, new_chat_session, start_run
from app.services.workflow_runs.runtime_target.switch import change_runtime
from tests.devices.device_support import device_with_grant, enable_device_runs
from tests.phased_workflow_fixtures import PHASE, admin_user, phased_definition, publish_phased

FOLDER = "/Users/dev/work/pay"


def _building_definition() -> dict:
    """The small phased workflow, its phase changing code and running the repository's tests, its gate linting."""
    definition = phased_definition()
    phase = copy.deepcopy(PHASE)
    phase["workflow_contract"]["capability_class"] = "change"
    phase["tool_policy"]["allowlist"] = [*phase["tool_policy"]["allowlist"], "run_test_suite"]
    definition["nodes"][1] = {**definition["nodes"][1], "label": "Fix and test", "config": phase}
    definition["nodes"][2]["config"]["checks"].append(
        {"type": "lint_passed", "params": {}, "blocking": True, "description": "Lint passes"})
    return definition


async def _setup(db):
    project = await enable_device_runs(db)
    admin = await admin_user(db)
    device, _ = await device_with_grant(db, admin, name="Mac", folders=[FOLDER], profiles=["governed"])
    return project, admin, device


def _device(device) -> dict:
    return {"kind": "device", "device_id": device.id, "folder": FOLDER, "profile": "governed"}


async def _runs(db, key: str) -> int:
    return int(await db.scalar(select(func.count()).select_from(WorkflowRun).where(WorkflowRun.workflow_key == key)))


@pytest.mark.asyncio
async def test_a_building_workflow_is_refused_on_the_server_before_anything_is_written(db):
    project, admin, _device_row = await _setup(db)
    key = await publish_phased(db, _building_definition())
    for target in ({"kind": "server"}, None):
        with pytest.raises(WorkflowRunError) as refused:
            await start_run(db, user=admin, workflow_key=key, project_id=project.id, runtime_target=target,
                            session=await new_chat_session(db, admin, project.id))
        assert (refused.value.code, refused.value.status_code) == ("server_build_not_allowed", 409)
        message = str(refused.value)
        assert message.startswith("This workflow builds or tests the repository (Fix and test, Evidence read)")
        assert "not allowed on the Octryx server" in message
        assert "Run it on your Mac (choose your device as the run location)" in message
    assert await _runs(db, key) == 0


@pytest.mark.asyncio
async def test_the_same_workflow_starts_on_the_device_or_a_terminal(db):
    project, admin, device = await _setup(db)
    key = await publish_phased(db, _building_definition())
    on_device = await start_run(db, user=admin, workflow_key=key, project_id=project.id,
                                runtime_target=_device(device), session=await new_chat_session(db, admin, project.id))
    assert on_device.context["runtime_target"]["kind"] == "device"
    on_terminal = await start_run(db, user=admin, workflow_key=key, project_id=project.id,
                                  runtime_target={"kind": "terminal"},
                                  session=await new_chat_session(db, admin, project.id))
    assert on_terminal.context["runtime_target"]["kind"] == "terminal"


@pytest.mark.asyncio
async def test_a_read_only_workflow_still_runs_on_the_server(db):
    project, admin, _device_row = await _setup(db)
    key = await publish_phased(db, phased_definition())
    run = await start_run(db, user=admin, workflow_key=key, project_id=project.id, runtime_target={"kind": "server"},
                          session=await new_chat_session(db, admin, project.id))
    assert run.context["runtime_target"]["kind"] == "server" and run.status in {"running", "waiting"}


@pytest.mark.asyncio
async def test_switching_a_building_run_onto_the_server_is_refused_and_recorded(db):
    project, admin, device = await _setup(db)
    key = await publish_phased(db, _building_definition())
    run = await start_run(db, user=admin, workflow_key=key, project_id=project.id, runtime_target=_device(device),
                          session=await new_chat_session(db, admin, project.id))
    with pytest.raises(WorkflowRunError) as refused:
        await change_runtime(db, run, user=admin, raw={"kind": "server"})
    assert refused.value.code == "server_build_not_allowed" and refused.value.persist is True
    assert run.context["runtime_target"]["kind"] == "device"  # the run stays where it was
    [event] = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == "server_build_refused"))).scalars()
    assert event.detail["reason"] == "server_build_not_allowed" and event.detail["where"] == "change_runtime"
    assert event.detail["steps"] == ["Fix and test", "Evidence read"] and event.actor_id == admin.id
