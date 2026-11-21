"""Target ``auto``: device-first with a seat, governed by rule or as fallback, always with a reason.

Contract: with the seat allowed, an online, free device of the requester with a folder known for the run's
repository gets the run with the seat profile; seat allowance used up, a rule forbidding the seat, or no usable
device each fall back to governed (on the device when usable, else the Server), and the stored target names
``resolved_from: auto`` and a readable reason.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import WorkflowRun
from app.models.runtime.agent_presence import AgentPresence
from app.services.agent_gateway.seat_policy import SeatDecision
from app.services.devices.hub import device_hub
from app.services.workflow_runs.runtime_target import auto
from app.services.workflow_runs.runtime_target.target import validate_target
from app.time_utils import utc_now
from tests.devices.device_support import RecordingConnection, device_with_grant, enable_device_runs
from tests.phased_workflow_fixtures import admin_user

REPO = "bitbucket:team/pay"
FOLDER = "/Users/dev/work/pay"


@pytest.fixture(autouse=True)
def _hub():
    device_hub.clear()
    yield
    device_hub.clear()


@pytest.fixture
def seat(monkeypatch):
    state = {"decision": SeatDecision(True)}

    async def decide(_db, _workspace_id, **_kwargs):
        return state["decision"]

    monkeypatch.setattr("app.services.agent_gateway.seat_policy.workspace_seat_decision", decide)
    return state


async def _setup(db, *, online: bool = True, known_folder: bool = True):
    project = await enable_device_runs(db)
    admin = await admin_user(db)
    device, _ = await device_with_grant(db, admin, name="Mac", folders=[FOLDER], profiles=["governed", "seat"])
    if online:
        device_hub._connections[device.id] = RecordingConnection(device.id)
    if known_folder:  # an earlier run of this repository on the device names the folder
        db.add(WorkflowRun(project_id=project.id, workflow_kind="phased", workflow_key="x", requested_by=admin.id,
                           status="completed", repository=REPO, context={"runtime_target": {
                               "kind": "device", "device_id": device.id, "folder": FOLDER, "profile": "seat"}}))
    await db.flush()
    return project, admin, device


async def _resolve(db, project, admin) -> dict:
    return await validate_target(db, user=admin, project_id=project.id, raw={"kind": "auto"}, repository=REPO)


@pytest.mark.asyncio
async def test_a_free_online_device_with_a_seat_gets_the_run(db, seat):
    project, admin, device = await _setup(db)
    target = await _resolve(db, project, admin)
    assert (target["kind"], target["device_id"], target["folder"], target["profile"]) == (
        "device", device.id, FOLDER, "seat")
    assert target["resolved_from"] == "auto" and target["reason"] == "seat on Mac"


@pytest.mark.asyncio
async def test_a_rule_forbidding_the_seat_runs_governed_on_the_device(db, seat):
    seat["decision"] = SeatDecision(False, "seat_classification_too_sensitive")
    project, admin, _device = await _setup(db)
    target = await _resolve(db, project, admin)
    assert (target["kind"], target["profile"]) == ("device", "governed")
    assert target["reason"] == "governed on Mac: a rule forbids the seat (seat_classification_too_sensitive)"


@pytest.mark.asyncio
async def test_used_up_allowance_falls_back_to_governed(db, seat):
    project, admin, _device = await _setup(db)
    db.add(AgentPresence(id="p1", session_key="k1", user_id=admin.id, project_id=project.id, profile="seat",
                         client="octryx-claude", device_key="device-auto", five_hour_pct=99.5, five_hour_resets_at=utc_now() + timedelta(hours=1),
                         allowance_updated_at=utc_now()))
    await db.flush()
    target = await _resolve(db, project, admin)
    assert target["profile"] == "governed" and "seat allowance used up" in target["reason"]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["offline", "no_folder"])
async def test_without_a_usable_device_the_server_runs_governed(db, seat, case):
    project, admin, _device = await _setup(db, online=case != "offline", known_folder=case != "no_folder")
    target = await _resolve(db, project, admin)
    assert target == {"kind": "server", "resolved_from": "auto", "reason": (
        "governed on the Server: no device of yours is online and free with a folder known for this repository")}
    assert auto.KIND_AUTO == "auto"
