"""Runs of one repository record (Work › Repositories) and Work › Runs cost with device jobs."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import (
    CodeRepository,
    DeviceJob,
    Project,
    Session,
    UsageEvent,
    User,
    UserDevice,
    WorkflowRun,
    WorkflowRunSession,
)
from tests.policy_engine_support import bearer


def uid() -> str:
    return str(uuid.uuid4())


@pytest.mark.asyncio
async def test_the_runs_of_a_repository_record_and_their_cost_with_device_jobs(client, db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=uid(), name="Kitchen helper", is_active=True, config={})
    db.add(project)
    await db.flush()
    # Bitbucket Server names its records "bitbucket/projects/<key>/repos/<slug>"; a run names "bitbucket:<key>/<slug>".
    record = CodeRepository(id=uid(), project_id=project.id, name="bitbucket/projects/CHEF/repos/kitchen-helper-mini",
                            repo_root="/repos/kitchen-helper-mini", provider="bitbucket")
    device = UserDevice(owner_user_id=admin.id, name="Mac", name_key=f"mac-{uid()[:6]}", os="macos", public_key="k")
    db.add_all([record, device])

    def run(repository: str | None) -> WorkflowRun:
        return WorkflowRun(id=uid(), project_id=project.id, workflow_kind="phased", workflow_key="team-delivery",
                           title="Team delivery", status="completed", requested_by=admin.id, repository=repository)

    ours, other, none = run("bitbucket:CHEF/kitchen-helper-mini"), run("github:alice-example/kitchen-helper"), run(None)
    db.add_all([ours, other, none])
    await db.flush()
    item = Session(id=uid(), user_id=admin.id, project_id=project.id, agent_type="diagnosis", status="active",
                   metadata_={})
    db.add(item)
    await db.flush()
    db.add(WorkflowRunSession(run_id=ours.id, session_id=item.id, role="child"))
    db.add(DeviceJob(device_id=device.id, owner_user_id=admin.id, session_id=item.id, workspace_id=project.id,
                     folder="/w", profile="seat", status="idle", cost_usd=9.0))
    # The job's calls are the gateway's seat rows: no API cost, their API equivalent apart.
    db.add(UsageEvent(id=str(uuid.uuid4()), session_id=item.id, user_id=admin.id, provider="anthropic_seat",
                      model="claude-sonnet-5-5", tokens_in=1, tokens_out=1, cost=0, list_cost=1.25,
                      cost_source="seat_subscription"))
    await db.commit()

    body = (await client.get("/api/v1/workflow-runs", params={"repository_id": record.id, "view": "work"},
                             headers=bearer(admin.id))).json()
    missing = await client.get("/api/v1/workflow-runs", params={"repository_id": uid()}, headers=bearer(admin.id))

    [row] = body["runs"]
    assert (row["id"], row["repository"]) == (ours.id, "bitbucket:CHEF/kitchen-helper-mini")
    assert (row["cost"], row["seat_api_equivalent"]) == (0.0, pytest.approx(1.25))  # a seat run shows its equivalent
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "repository_not_found"
