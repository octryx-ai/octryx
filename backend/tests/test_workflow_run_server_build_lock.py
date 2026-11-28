"""A run that builds or tests the repository never runs on the server: refused at start or on a switch,
while device and terminal targets and read-only workflows still start."""

from __future__ import annotations

import copy

import pytest

from app.services.workflow_runs.records import new_chat_session, start_run
from tests.devices.device_support import device_with_grant, enable_device_runs
from tests.phased_workflow_fixtures import PHASE, admin_user, phased_definition, publish_phased
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

FOLDER = "/Users/dev/work/pay"


def _building_definition() -> dict:
    definition = phased_definition()
    phase = copy.deepcopy(PHASE)
    phase["workflow_contract"]["capability_class"] = "change"
    phase["tool_policy"]["allowlist"] = [*phase["tool_policy"]["allowlist"], "run_test_suite"]
    definition["nodes"][1] = {**definition["nodes"][1], "label": "Fix and test", "config": phase}
    definition["nodes"][2]["config"]["checks"].append(
        {"type": "test_command_passed", "params": {}, "blocking": True, "description": "Tests pass"})
    return definition


async def _setup(db):
    project = await enable_device_runs(db)
    admin = await admin_user(db)
    device, _ = await device_with_grant(db, admin, name="Mac", folders=[FOLDER], profiles=["governed"])
    return project, admin, device


def _device(device) -> dict:
    return {"kind": "device", "device_id": device.id, "folder": FOLDER, "profile": "governed"}


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


