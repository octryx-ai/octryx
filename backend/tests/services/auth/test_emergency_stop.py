"""Emergency stop (gap #3): one explicit, audited admin action pauses a Workspace's machine work and stops its device
jobs; runs waiting for a person, other Workspaces and non-admins are left alone, and Continue resumes a run."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import DeviceJob, KillSwitchLog, Project, Session, User, UserDevice, UserProject, WorkflowRun
from tests.policy_engine_support import bearer

ROUTE = "/api/v1/admin/operations/emergency-stop"


def uid() -> str:
    return str(uuid.uuid4())


async def _user(db, label: str, memberships: dict[str, str]) -> User:
    user = User(id=uid(), username=f"{label}-{uid()[:8]}", email=f"{uid()}@example.test", password_hash="!")
    db.add(user)
    await db.flush()
    for project_id, role in memberships.items():
        db.add(UserProject(user_id=user.id, project_id=project_id, role=role))
    await db.flush()
    return user


async def _world(db) -> dict:
    alpha = Project(id=uid(), name="Kitchen helper", is_active=True, config={})
    beta = Project(id=uid(), name="Other", is_active=True, config={})
    db.add_all([alpha, beta])
    await db.flush()
    lead = await _user(db, "lead", {alpha.id: "admin"})
    member = await _user(db, "member", {alpha.id: "member"})
    device = UserDevice(owner_user_id=member.id, name="Mac", name_key=f"mac-{uid()[:6]}", os="macos", public_key="k")
    chat = Session(id=uid(), user_id=member.id, agent_type="diagnosis", status="active", metadata_={})
    db.add_all([device, chat])
    await db.flush()

    def run(project, status, **extra) -> WorkflowRun:
        return WorkflowRun(id=uid(), project_id=project.id, workflow_kind="phased", workflow_key="team-delivery",
                           title=f"{project.name} {status}", status=status, requested_by=member.id,
                           current_node_id="work", **extra)

    working = run(alpha, "running")
    on_device = run(alpha, "waiting", waiting_kind="waiting_for_device")
    asks_person = run(alpha, "waiting", waiting_kind="waiting_for_reply")
    elsewhere = run(beta, "running")
    db.add_all([working, on_device, asks_person, elsewhere])
    job = DeviceJob(device_id=device.id, owner_user_id=member.id, session_id=chat.id, workspace_id=alpha.id,
                    folder="/kitchen-helper/.octryx-items/core-domain", profile="seat", status="running", turn_state="accepted")
    other_job = DeviceJob(device_id=device.id, owner_user_id=member.id, session_id=chat.id, workspace_id=beta.id,
                          folder="/other", profile="seat", status="running", turn_state="accepted")
    db.add_all([job, other_job])
    await db.commit()
    return {"alpha": alpha, "beta": beta, "lead": lead, "member": member, "working": working,
            "on_device": on_device, "asks_person": asks_person, "elsewhere": elsewhere, "job": job,
            "other_job": other_job}


@pytest.mark.asyncio
async def _reloaded(db, row):
    # The stop's own session is this test's session: it hands back the rows it read as platform maintenance.
    return await db.get(type(row), row.id, populate_existing=True)


async def test_a_workspace_admin_previews_and_stops_the_machine_work_of_their_workspace(client, db):
    w = await _world(db)
    alpha = w["alpha"].id

    preview = (await client.get(f"{ROUTE}/preview", params={"workspace_id": alpha}, headers=bearer(w["lead"].id)))
    no_reason = await client.post(ROUTE, json={"workspace_id": alpha, "reason": " "}, headers=bearer(w["lead"].id))
    stopped = await client.post(ROUTE, json={"workspace_id": alpha, "reason": "R1 loop"}, headers=bearer(w["lead"].id))

    assert preview.status_code == 200
    assert {row["id"] for row in preview.json()["runs"]} == {w["working"].id, w["on_device"].id}
    assert [row["id"] for row in preview.json()["device_jobs"]] == [w["job"].id]
    assert no_reason.status_code == 422 and no_reason.json()["detail"]["code"] == "reason_required"
    assert stopped.status_code == 200
    body = stopped.json()
    assert set(body["paused_runs"]) == {w["working"].id, w["on_device"].id}
    assert body["stopped_device_jobs"] == [w["job"].id]
    for name, status in (("working", "paused"), ("on_device", "paused"), ("asks_person", "waiting"),
                         ("elsewhere", "running")):
        w[name] = await _reloaded(db, w[name])
        assert w[name].status == status, name
    pause = w["working"].node_state["pause"]
    assert (w["working"].pause_reason, pause["code"]) == ("emergency_stop", "emergency_stop")
    assert pause["resume"] == {"kind": "restart", "node_id": "work"} and "R1 loop" in pause["message"]
    w["job"], w["other_job"] = await _reloaded(db, w["job"]), await _reloaded(db, w["other_job"])
    assert w["job"].stop_state == "pending" and w["other_job"].stop_state is None
    log = (await db.execute(select(KillSwitchLog).where(KillSwitchLog.id == body["log_id"]))).scalar_one()
    assert (log.target_type, log.project_id, log.user_id, log.reason) == ("project", alpha, w["lead"].id, "R1 loop")
    history = (await client.get(f"{ROUTE}/history", params={"workspace_id": alpha},
                                headers=bearer(w["lead"].id))).json()["stops"]
    assert history[0]["id"] == body["log_id"] and history[0]["by"]["id"] == w["lead"].id
    live = (await client.get("/api/v1/admin/operations/live", params={"workspace_id": alpha},
                             headers=bearer(w["lead"].id))).json()
    row = next(item for item in live["runs"] if item["id"] == w["working"].id)
    assert (row["status"], row["pause_reason"]) == ("paused", "emergency_stop")


@pytest.mark.asyncio
async def test_members_other_workspaces_and_the_whole_platform_are_refused(client, db):
    w = await _world(db)

    member = await client.post(ROUTE, json={"workspace_id": w["alpha"].id, "reason": "x"},
                               headers=bearer(w["member"].id))
    other = await client.post(ROUTE, json={"workspace_id": w["beta"].id, "reason": "x"},
                              headers=bearer(w["lead"].id))
    unknown = await client.post(ROUTE, json={"workspace_id": str(uuid.uuid4()), "reason": "x"},
                                headers=bearer(w["lead"].id))
    platform = await client.post(ROUTE, json={"reason": "x"}, headers=bearer(w["lead"].id))

    assert member.status_code == 403
    # A Workspace the lead is no member of answers exactly like one that does not exist.
    assert other.status_code == 404 and other.json()["detail"]["code"] == "project_not_found"
    assert (unknown.status_code, unknown.json()["detail"]) == (other.status_code, other.json()["detail"])
    assert platform.status_code == 403 and platform.json()["detail"]["code"] == "platform_admin_required"
    await db.refresh(w["working"])
    assert w["working"].status == "running"


@pytest.mark.asyncio
async def test_a_stopped_run_is_stopped_in_live_and_attention_in_problems_never_a_broadcast_problem(client, db):
    from app.services.problems import alerts

    w = await _world(db)
    alpha = w["alpha"].id
    await alerts.sweep(db)  # baseline: the platform has been watching already
    await client.post(ROUTE, json={"workspace_id": alpha, "reason": "R1 loop"}, headers=bearer(w["lead"].id))

    live = (await client.get(f"/api/v1/admin/operations/live?workspace_id={alpha}",
                             headers=bearer(w["lead"].id))).json()
    problems = (await client.get(f"/api/v1/admin/problems?workspace_id={alpha}&kind=run",
                                 headers=bearer(w["lead"].id))).json()["problems"]
    swept = await alerts.sweep(db)

    states = {row["id"]: row["state"] for row in live["runs"]}
    assert states[w["working"].id] == "stopped" and states[w["on_device"].id] == "stopped"
    assert live["counts"]["stopped"] == 2 and live["counts"]["problem"] == 0
    stopped = [item for item in problems if item["object"]["id"] == w["working"].id]
    assert [(item["severity"], item["key"].rsplit(":", 1)[-1]) for item in stopped] == [("attention", "stopped")]
    assert swept["raised"] == 0
