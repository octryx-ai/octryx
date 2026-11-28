"""Operations › Live: where each active run is, its items and jobs, cost, state, devices, seats and scope."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import (
    AgentPresence,
    DeviceJob,
    Project,
    Session,
    UsageEvent,
    User,
    UserDevice,
    UserProject,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowRunSession,
)
from app.services.operations import fleet
from app.time_utils import utc_now
from tests.policy_engine_support import bearer

ADMIN_ROUTE = "/api/v1/admin/operations/live"


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


async def _session(db, owner: User, run: WorkflowRun, role: str) -> Session:
    session = Session(id=uid(), user_id=owner.id, project_id=run.project_id, agent_type="diagnosis",
                      status="active", metadata_={})
    db.add(session)
    await db.flush()
    db.add(WorkflowRunSession(run_id=run.id, session_id=session.id, role=role))
    return session


async def _world(db) -> dict:
    # Taken when the rows are written, not at import: in a long parallel suite the test can run long after
    # collection, and "recent" rows would be older than the live window and come back in another order.
    NOW = utc_now()  # noqa: N806 - the name the rows below were written with
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    alpha = Project(id=uid(), name="Kitchen helper", is_active=True, config={})
    beta = Project(id=uid(), name="Other", is_active=True, config={})
    db.add_all([alpha, beta])
    await db.flush()
    member = await _user(db, "member", {alpha.id: "member"})
    device = UserDevice(owner_user_id=member.id, name="Mac", name_key=f"mac-{uid()[:6]}", os="macos",
                        public_key="k", last_seen_at=NOW, client_version="0.3.0")
    db.add(device)
    await db.flush()

    def run(project, **extra) -> WorkflowRun:
        return WorkflowRun(id=uid(), project_id=project.id, workflow_kind="phased", workflow_key="team-delivery",
                           title=extra.pop("title", "Team delivery"), requested_by=member.id,
                           updated_at=extra.pop("updated_at", NOW - timedelta(seconds=30)), **extra)

    team = run(alpha, status="running", current_node_id="work",
               context={"work": {"items": {
                   "core-domain": {"title": "Core", "status": "running", "iteration": 1, "model": "haiku"},
                   "frontend-shell": {"title": "Shell", "status": "pending", "iteration": 1},
               }}})
    waiting = run(alpha, title="Spec writing", status="waiting", waiting_kind="waiting_for_reply")
    quiet = run(alpha, title="Ticket delivery", status="running", updated_at=NOW - timedelta(hours=1))
    other = run(beta, title="Elsewhere", status="running")
    finished = run(alpha, title="Done", status="completed")
    db.add_all([team, waiting, quiet, other, finished])
    await db.flush()
    main = await _session(db, member, team, "main")
    item_session = await _session(db, member, team, "child")
    team.context["work"]["items"]["core-domain"]["session_id"] = item_session.id
    db.add(DeviceJob(device_id=device.id, owner_user_id=member.id, session_id=item_session.id,
                     workspace_id=alpha.id, folder="/kitchen-helper/.octryx-items/core-domain", profile="seat",
                     status="running", turn_state="accepted", cost_usd=9.0, updated_at=NOW - timedelta(seconds=5)))
    # The job's calls are the gateway's seat rows: API cost 0, their API equivalent apart.
    db.add(UsageEvent(id=uid(), session_id=item_session.id, user_id=member.id, provider="anthropic_seat",
                      model="claude-sonnet-5-5", tokens_in=1, tokens_out=1, cost=0, list_cost=0.25,
                      cost_source="seat_subscription", created_at=NOW - timedelta(minutes=1)))
    db.add(UsageEvent(id=uid(), session_id=main.id, user_id=member.id, provider="bedrock", model="m", tokens_in=1,
                      tokens_out=1, cost=0.5, created_at=NOW - timedelta(minutes=1)))
    # The loop shape: core-domain dispatched again and again in the last minutes.
    for n in range(11):
        db.add(WorkflowRunEvent(run_id=team.id, kind="work_item", created_at=NOW - timedelta(seconds=n),
                                detail={"item": "core-domain", "status": "running", "iteration": 1}))
    db.add(AgentPresence(id=uid(), session_key=uid(), user_id=member.id, project_id=alpha.id, profile="seat",
                         client="octryx-claude", device_key="device-live", five_hour_pct=91.0, last_seen_at=NOW))
    await db.flush()
    return {"admin": admin, "member": member, "alpha": alpha, "beta": beta, "device": device, "team": team,
            "waiting": waiting, "quiet": quiet, "other": other, "finished": finished, "main": main}


def _run(body: dict, run_id: str) -> dict | None:
    return next((row for row in body["runs"] if row["id"] == run_id), None)


@pytest.mark.asyncio
async def test_the_member_sees_where_each_run_is_its_items_cost_and_state(client, db, monkeypatch):
    monkeypatch.setattr(fleet, "served_version", lambda: "0.3.2")
    world = await _world(db)
    alpha = world["alpha"].id

    response = await client.get(f"/api/v1/workspaces/{alpha}/operations/live", headers=bearer(world["member"].id))

    assert response.status_code == 200
    body = response.json()
    assert body["viewer"] == {"id": world["member"].id}
    ids = [row["id"] for row in body["runs"]]
    assert world["other"].id not in ids and world["finished"].id not in ids
    # Most urgent first: the loop, then the silent run, then the run that waits for a person.
    assert ids == [world["team"].id, world["quiet"].id, world["waiting"].id]
    team = _run(body, world["team"].id)
    assert team["state"] == "looping"
    assert {p["reason_code"] for p in team["problems"]} == {"looping"}
    assert team["workspace"] == {"id": alpha, "name": "Kitchen helper"}
    assert team["requested_by"]["is_me"] is True and team["session_id"] == world["main"].id
    assert (team["cost_usd"], team["seat_api_equivalent_usd"]) == (pytest.approx(0.5), pytest.approx(0.25))
    core, shell = team["items"]
    assert (core["id"], core["dispatches_5m"], core["job"]["status"]) == ("core-domain", 11, "running")
    assert core["job"]["folder"].endswith("core-domain") and shell["job"] is None
    assert _run(body, world["quiet"].id)["state"] == "silent"
    assert _run(body, world["waiting"].id)["state"] == "needs_you"
    assert body["counts"]["looping"] == 1 and body["counts"]["needs_you"] == 1
    assert body["counts"]["cost_24h_usd"] == pytest.approx(0.5)  # the device job's own figure is never counted
    assert body["counts"]["seat_api_equivalent_24h_usd"] == pytest.approx(0.25)
    device = next(row for row in body["devices"] if row["id"] == world["device"].id)
    assert (device["jobs_running"], device["outdated"], device["owner"]["is_me"]) == (1, True, True)
    assert body["seats"][0]["five_hour_pct"] == 91.0


@pytest.mark.asyncio
async def test_scope_admin_route_for_admins_workspace_route_for_members(client, db):
    world = await _world(db)

    admin = await client.get(ADMIN_ROUTE, headers=bearer(world["admin"].id))
    member_admin_route = await client.get(ADMIN_ROUTE, headers=bearer(world["member"].id))
    member_other = await client.get(f"/api/v1/workspaces/{world['beta'].id}/operations/live",
                                    headers=bearer(world["member"].id))

    assert admin.status_code == 200
    assert {world["team"].id, world["other"].id} <= {row["id"] for row in admin.json()["runs"]}
    assert member_admin_route.status_code == 403
    assert member_admin_route.json()["detail"]["code"] == "admin_required"
    assert member_other.status_code == 404


def test_the_workflow_title_drops_the_ticket_key_the_page_shows_anyway():
    from app.services.operations.runs import workflow_title

    assert workflow_title("Ticket delivery · OCX-22", "OCX-22") == "Ticket delivery"
    assert workflow_title("Team delivery", "OCX-22") == "Team delivery"
    assert workflow_title("Spec · CHEF-7 · draft", "CHEF-7") == "Spec · draft"
    assert workflow_title("Ticket delivery · OCX-22", None) == "Ticket delivery · OCX-22"


@pytest.mark.parametrize(("client", "served", "outdated"), [
    ("0.3.0", "0.3.2", True),
    ("0.10.0", "0.9.9", False),
    ("0.3", "0.3.0", False),
    ("0.3.0rc1", "0.3.0", True),
    ("0.3.0a2", "0.3.0b1", True),
    ("0.2.0+1a2b3c4d5e6f", "0.3.0+000000000000", True),
    ("0.3.0+1a2b3c4d5e6f", "0.3.0+1a2b3c4d5e6f", False),
    ("0.3.0+1a2b3c4d5e6f", "0.3.0+ffffffffffff", True),
    ("0.4.0+1a2b3c4d5e6f", "0.3.0+ffffffffffff", False),
    ("nightly", "0.3.0", True),
    (None, "0.3.0", False),
])
def test_outdated_compares_versions_without_packaging(client, served, outdated):
    assert fleet._outdated(client, served) is outdated
