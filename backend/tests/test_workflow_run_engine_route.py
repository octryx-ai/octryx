"""A run's coding engine and route (phone run line): from its newest device job, else from a gateway
session of the run; nothing guessed for a run without either."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import DeviceJob, Project, Session, User, UserDevice, WorkflowRun, WorkflowRunSession
from app.services.workflow_runs.run_engine import route_of, run_engine_routes
from app.time_utils import utc_now
from tests.policy_engine_support import bearer


def uid() -> str:
    return str(uuid.uuid4())


def test_the_route_of_a_profile():
    assert route_of("seat") == route_of("local:private") == "own_subscription"
    assert route_of("governed") == "company_model"
    assert route_of("") is None and route_of(None) is None and route_of("work") is None


@pytest.mark.asyncio
async def test_engine_and_route_of_each_run_in_the_list_and_the_run_view(client, db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=uid(), name=f"ws-{uid()[:6]}", is_active=True, config={})
    device = UserDevice(owner_user_id=admin.id, name="Mac", name_key=f"mac-{uid()[:6]}", os="macos", public_key="k")
    db.add_all([project, device])
    await db.flush()

    def run() -> WorkflowRun:
        return WorkflowRun(id=uid(), project_id=project.id, workflow_kind="phased", workflow_key="team-delivery",
                           title="Team delivery", status="completed", requested_by=admin.id)

    def session(metadata: dict | None = None) -> Session:
        return Session(id=uid(), user_id=admin.id, project_id=project.id, agent_type="diagnosis", status="active",
                       metadata_=metadata or {})

    on_mac, in_terminal, on_server = run(), run(), run()
    main, child, gateway, server = session(), session(), session({"gateway_profile": "governed", "engine": "codex"}), \
        session()
    db.add_all([on_mac, in_terminal, on_server, main, child, gateway, server])
    await db.flush()
    db.add_all([
        WorkflowRunSession(run_id=on_mac.id, session_id=main.id, role="main"),
        WorkflowRunSession(run_id=on_mac.id, session_id=child.id, role="child"),
        WorkflowRunSession(run_id=in_terminal.id, session_id=gateway.id, role="main"),
        WorkflowRunSession(run_id=on_server.id, session_id=server.id, role="main"),
        # An older Claude Code job on the governed route, then the newest: Codex on the person's own subscription.
        DeviceJob(device_id=device.id, owner_user_id=admin.id, session_id=main.id, workspace_id=project.id,
                  folder="/w", profile="governed", status="idle", created_at=utc_now() - timedelta(hours=1)),
        DeviceJob(device_id=device.id, owner_user_id=admin.id, session_id=child.id, workspace_id=project.id,
                  folder="/w", profile="seat", status="idle", engine="codex", created_at=utc_now()),
    ])
    await db.commit()

    routes = await run_engine_routes(db, [on_mac.id, in_terminal.id, on_server.id])
    assert routes == {
        on_mac.id: {"engine": "codex", "route": "own_subscription"},
        in_terminal.id: {"engine": "codex", "route": "company_model"},
        on_server.id: {"engine": None, "route": None},
    }

    listed = (await client.get("/api/v1/workflow-runs", params={"project_id": project.id},
                               headers=bearer(admin.id))).json()["runs"]
    assert {row["id"]: (row["engine"], row["route"]) for row in listed} == {
        on_mac.id: ("codex", "own_subscription"), in_terminal.id: ("codex", "company_model"),
        on_server.id: (None, None)}
    view = (await client.get(f"/api/v1/workflow-runs/{on_mac.id}", headers=bearer(admin.id))).json()["run"]
    assert (view["engine"], view["route"]) == ("codex", "own_subscription")
