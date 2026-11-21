"""Activity problems reach the people they concern: the attention queue (companion, inbox) and the phone push.

A run that loops for minutes must not go unnoticed.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import DeviceJob, Project, Session, User, UserDevice, UserProject, WorkflowRun, WorkflowRunEvent
from app.services.attention.activity_items import activity_entries
from app.services.mobile.push import group_of, messages_for
from app.time_utils import utc_now
from tests.policy_engine_support import bearer


def uid() -> str:
    return str(uuid.uuid4())


async def _user(db, label: str, project: Project) -> User:
    user = User(id=uid(), username=f"{label}-{uid()[:8]}", email=f"{uid()}@example.test", password_hash="!")
    db.add(user)
    await db.flush()
    db.add(UserProject(user_id=user.id, project_id=project.id, role="member"))
    await db.flush()
    return user


@pytest.mark.asyncio
async def test_a_looping_run_reaches_its_requester_and_responsible_once_and_nobody_else(client, db):
    now = utc_now()  # per test: the activity windows count back from the real now
    project = Project(id=uid(), name="Kitchen helper", is_active=True, config={})
    db.add(project)
    await db.flush()
    owner = await _user(db, "owner", project)
    lead = await _user(db, "lead", project)
    other = await _user(db, "other", project)
    run = WorkflowRun(id=uid(), project_id=project.id, workflow_kind="phased", workflow_key="team-delivery",
                      title="Team delivery", status="running", requested_by=owner.id,
                      responsible_user_id=lead.id, updated_at=now)
    db.add(run)
    await db.flush()
    for n in range(12):
        db.add(WorkflowRunEvent(run_id=run.id, kind="work_item", created_at=now - timedelta(seconds=3 * n),
                                detail={"item": "core-domain", "status": "running", "iteration": 1}))
    await db.commit()

    owner_queue = (await client.get("/api/v1/attention", headers=bearer(owner.id))).json()
    lead_entries = await activity_entries(db, lead)
    other_entries = await activity_entries(db, other)

    [entry] = [item for item in owner_queue["items"] if item["code"] == "looping"]
    assert entry["key"] == f"activity:run:{run.id}:looping"
    assert (entry["kind"], entry["severity"], entry["workspace"]["name"]) == ("problem", "warning", "Kitchen helper")
    assert "core-domain" in entry["title"] and entry["link"]["href"].startswith("/chat?")
    assert [item["key"] for item in lead_entries] == [entry["key"]]
    assert other_entries == []
    # The loop goes on: the window slides, the key does not, so the phone is told once.
    db.add(WorkflowRunEvent(run_id=run.id, kind="work_item", created_at=utc_now(),
                            detail={"item": "core-domain", "status": "running", "iteration": 1}))
    await db.commit()
    assert [item["key"] for item in await activity_entries(db, owner)] == [entry["key"]]
    # On the phone it is a "Problem" push whose text says what is wrong, opening that entry.
    assert group_of(entry) == "problem"
    [message] = messages_for([entry], badge=0)
    assert message["title"] == "Problem" and message["body"].startswith("Loop detected") and message["body"].endswith("· Kitchen helper")
    assert message["url"] == f"/m/#item={entry['key']}"


@pytest.mark.asyncio
async def test_a_stalled_device_job_reaches_only_its_owner(db):
    now = utc_now()  # per test: the activity windows count back from the real now
    project = Project(id=uid(), name="Kitchen helper", is_active=True, config={})
    db.add(project)
    await db.flush()
    owner = await _user(db, "owner", project)
    other = await _user(db, "other", project)
    device = UserDevice(owner_user_id=owner.id, name="Mac", name_key=f"mac-{uid()[:6]}", os="macos",
                        public_key="k", last_seen_at=now)
    chat = Session(id=uid(), user_id=owner.id, agent_type="diagnosis", status="active", metadata_={})
    db.add_all([device, chat])
    await db.flush()
    job = DeviceJob(device_id=device.id, owner_user_id=owner.id, session_id=chat.id, workspace_id=project.id,
                    folder="/kitchen-helper/.octryx-items/fix-effort", profile="seat", status="running",
                    updated_at=now - timedelta(minutes=30))
    db.add(job)
    await db.flush()

    [entry] = await activity_entries(db, owner)
    assert entry["code"] == "job_stalled" and entry["subtitle"] == "fix-effort"
    assert entry["key"].startswith(f"activity:device:{job.id}:job_stalled:")
    assert await activity_entries(db, other) == []
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    assert await activity_entries(db, admin) == []
