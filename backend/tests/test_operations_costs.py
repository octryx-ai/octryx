"""Cost report (gap #4): what the runs of a window cost and delivered, per workflow / work item / person, scoped."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import (
    DeviceJob,
    Project,
    Session,
    UsageEvent,
    User,
    UserDevice,
    UserProject,
    WorkflowRun,
    WorkflowRunSession,
)
from app.models.runtime.secure_work import WorkItem
from app.services.auth import create_access_token
from app.time_utils import utc_now

ROUTE = "/api/v1/admin/operations/costs"
NOW = utc_now()


def uid() -> str:
    return str(uuid.uuid4())


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def _world(db) -> dict:
    alpha = Project(id=uid(), name="Kitchen helper", is_active=True, config={})
    beta = Project(id=uid(), name="Other", is_active=True, config={})
    db.add_all([alpha, beta])
    await db.flush()
    lead = User(id=uid(), username=f"lead-{uid()[:8]}", email=f"{uid()}@example.test", password_hash="!")
    member = User(id=uid(), username=f"member-{uid()[:8]}", email=f"{uid()}@example.test", password_hash="!")
    db.add_all([lead, member])
    await db.flush()
    db.add_all([UserProject(user_id=lead.id, project_id=alpha.id, role="admin"),
                UserProject(user_id=member.id, project_id=alpha.id, role="member")])
    item = WorkItem(id=uid(), project_id=alpha.id, source_type="jira", source_id=uid(), source_key="CHEF-7",
                    title="Cook mode")
    device = UserDevice(owner_user_id=member.id, name="Mac", name_key=f"mac-{uid()[:6]}", os="macos", public_key="k")
    db.add_all([item, device])
    await db.flush()

    async def run(project, key, status, *, item_id=None, pr=None, job_cost=None, usage_cost=None, age_days=1):
        run = WorkflowRun(id=uid(), project_id=project.id, workflow_kind="phased", workflow_key=key, title=key,
                          status=status, requested_by=member.id, work_item_id=item_id,
                          pull_request={"url": pr} if pr else None, created_at=NOW - timedelta(days=age_days))
        db.add(run)
        await db.flush()
        for cost, on_device in ((job_cost, True), (usage_cost, False)):
            if cost is None:
                continue
            session = Session(id=uid(), user_id=member.id, project_id=project.id, agent_type="diagnosis",
                              status="active", metadata_={})
            db.add(session)
            await db.flush()
            db.add(WorkflowRunSession(run_id=run.id, session_id=session.id, role="child"))
            if on_device:
                # The device job's own figure is never counted: its calls are the gateway's seat rows.
                db.add(DeviceJob(device_id=device.id, owner_user_id=member.id, session_id=session.id,
                                 workspace_id=project.id, folder="/w", profile="seat", status="idle", cost_usd=99.0))
                db.add(UsageEvent(id=uid(), session_id=session.id, user_id=member.id, provider="anthropic_seat",
                                  model="claude-sonnet-5-5", tokens_in=1, tokens_out=1, cost=0, list_cost=cost,
                                  cost_source="seat_subscription"))
            else:
                db.add(UsageEvent(id=uid(), session_id=session.id, user_id=member.id, provider="bedrock", model="m",
                                  tokens_in=1, tokens_out=1, cost=cost))
        await db.flush()
        return run

    await run(alpha, "team-delivery", "completed", item_id=item.id, pr="https://github.test/pr/5", job_cost=1.5,
              usage_cost=0.5)
    await run(alpha, "team-delivery", "stopped", item_id=item.id, job_cost=1.0)
    await run(alpha, "spec-writing", "completed", item_id=item.id, usage_cost=0.25)
    await run(alpha, "team-delivery", "completed", job_cost=9.0, age_days=30)  # outside 7 days
    await run(beta, "team-delivery", "completed", job_cost=5.0)  # other Workspace
    await db.commit()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    return {"alpha": alpha, "beta": beta, "lead": lead, "member": member, "item": item, "admin": admin}


@pytest.mark.asyncio
async def test_cost_and_outcome_per_workflow_and_work_item_in_the_workspace(client, db):
    w = await _world(db)

    body = (await client.get(ROUTE, params={"workspace_id": w["alpha"].id, "days": 7},
                             headers=_headers(w["lead"]))).json()
    by_item = (await client.get(ROUTE, params={"workspace_id": w["alpha"].id, "group": "work_item"},
                                headers=_headers(w["lead"]))).json()

    # API cost and the seat calls' API equivalent, never added together.
    assert body["totals"] == {"runs": 3, "delivered": 2, "pull_requests": 1, "cost_usd": pytest.approx(0.75),
                              "seat_api_equivalent_usd": pytest.approx(2.5), "seat_unpriced_calls": 0,
                              "cost_per_delivered_usd": pytest.approx(0.375)}
    team, spec = sorted(body["groups"], key=lambda row: row["key"], reverse=True)
    assert (team["key"], team["runs"], team["delivered"], team["pull_requests"]) == ("team-delivery", 2, 1, 1)
    assert team["cost_usd"] == pytest.approx(0.5) and team["seat_api_equivalent_usd"] == pytest.approx(2.5)
    assert (spec["key"], spec["cost_usd"], spec["seat_api_equivalent_usd"]) == ("spec-writing", pytest.approx(0.25),
                                                                                  0.0)
    [item] = by_item["groups"]
    assert (item["key"], item["label"], item["runs"]) == (w["item"].id, "CHEF-7 Cook mode", 3)


@pytest.mark.asyncio
async def test_scope_and_filters(client, db):
    w = await _world(db)

    member = await client.get(ROUTE, headers=_headers(w["member"]))
    other = (await client.get(ROUTE, params={"workspace_id": w["beta"].id}, headers=_headers(w["lead"]))).json()
    bad = await client.get(ROUTE, params={"group": "planet"}, headers=_headers(w["admin"]))
    platform = (await client.get(ROUTE, params={"group": "workspace"}, headers=_headers(w["admin"]))).json()

    assert member.status_code == 403
    assert other["totals"]["runs"] == 0  # a Workspace admin sees only what they administer
    assert bad.status_code == 422 and bad.json()["detail"]["field"] == "group"
    labels = {row["label"] for row in platform["groups"]}
    assert {"Kitchen helper", "Other"} <= labels
