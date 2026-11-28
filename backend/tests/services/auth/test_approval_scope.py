"""Contract: approvals are seen and decided only by those who own their run (or an admin); others get 404."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Approval, Project, Session, User
from app.models.project.task import Task, TaskRun
from app.services.auth.tokens import hash_password
from app.services.channel_router_runtime import ChannelMessageRouter
from tests.policy_engine_support import bearer


async def _user(db, label: str) -> User:
    user = User(
        id=str(uuid.uuid4()),
        username=f"{label}-{uuid.uuid4().hex[:8]}",
        email=f"{label}-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("scope-Test-Pw-123"),
        display_name=label,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    return user


async def _approvals_of(db, owner: User) -> tuple[Approval, Approval, Approval]:
    session = Session(id=str(uuid.uuid4()), user_id=owner.id, agent_type="change", status="active", metadata_={})
    task = Task(dispatch_binding="task_definition", id=str(uuid.uuid4()), name=f"task-{owner.username}", owner_id=owner.id)
    workspace = Project(id=str(uuid.uuid4()), name=f"ws-{owner.username}")
    db.add_all([session, task, workspace])
    await db.flush()
    run = TaskRun(id=str(uuid.uuid4()), task_id=task.id, started_by=owner.id, status="waiting_approval")
    db.add(run)
    await db.flush()
    session_approval = Approval(id=str(uuid.uuid4()), session_id=session.id, requested_by=owner.id, action="deploy")
    run_approval = Approval(id=str(uuid.uuid4()), task_run_id=run.id, requested_by=owner.id, action="rollout")
    review = Approval(
        id=str(uuid.uuid4()), requested_by=owner.id, workspace_id=workspace.id, action="model_policy.publish:r:d"
    )
    db.add_all([session_approval, run_approval, review])
    await db.commit()
    return session_approval, run_approval, review


async def _status(db, approval_id: str) -> str:
    await db.rollback()
    return (await db.execute(select(Approval.status).where(Approval.id == approval_id))).scalar_one()


@pytest.mark.asyncio
async def test_approvals_are_listed_and_decided_only_by_their_owners(client, db, auth_headers):
    owner, other = await _user(db, "owner"), await _user(db, "other")
    owned = {a.id for a in await _approvals_of(db, owner)}
    others = {a.id for a in await _approvals_of(db, other)}

    def _ids(response) -> set[str]:
        assert response.status_code == 200
        return {item["id"] for item in response.json()}

    listed = _ids(await client.get("/api/v1/approvals", headers=bearer(other.id)))
    assert others <= listed and not (owned & listed)
    assert owned <= _ids(await client.get("/api/v1/approvals", headers=bearer(owner.id)))
    assert owned | others <= _ids(await client.get("/api/v1/approvals", headers=auth_headers))

    for approval_id in owned:
        for action in ("approve", "reject"):
            refused = await client.post(
                f"/api/v1/approvals/{approval_id}/{action}", json={"reason": "x"}, headers=bearer(other.id)
            )
            assert refused.status_code == 404, (approval_id, action, refused.status_code)
        assert await _status(db, approval_id) == "pending"

    run_approval = (
        await db.execute(select(Approval).where(Approval.id.in_(owned), Approval.task_run_id.is_not(None)))
    ).scalar_one()
    decided = await client.post(
        f"/api/v1/approvals/{run_approval.id}/approve", json={"reason": "ok"}, headers=bearer(owner.id)
    )
    assert decided.status_code == 200 and decided.json()["status"] == "approved"
    assert decided.json()["approved_by"] == owner.id


class _Plugin:
    plugin_id = "msteams"
    config: dict = {}
    require_registered_user = False  # chat would run as the channel's service user
    allowed_roles: list = []
    require_mention = False
    thread_followup_policy = "mention_once_per_thread"

    def __init__(self, sender_mappings: dict[str, str] | None = None) -> None:
        self.sender_mappings = sender_mappings or {}
        self.sent: list[str] = []

    async def send_message(self, target: str, content: str, **kwargs):
        self.sent.append(content)
        return True


def _router(db) -> ChannelMessageRouter:
    class _Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return db

        async def __aexit__(self, *exc):
            return False

    router = ChannelMessageRouter()
    router._session_factory = _Factory()
    return router


@pytest.mark.asyncio
async def test_an_unresolved_channel_sender_never_decides(db):
    owner = await _user(db, "owner")
    _session_approval, run_approval, _review = await _approvals_of(db, owner)
    router = _router(db)
    plugin = _Plugin()
    await router._handle_message("wave3", plugin, {"sender_id": "unknown-sender", "content": f"approve {run_approval.id}"})
    assert plugin.sent == [
        "channel_sender_unresolved: this sender is not linked to a platform user, so it cannot decide approvals."
    ]
    assert await _status(db, run_approval.id) == "pending"

    linked = _Plugin(sender_mappings={"owner-sender": owner.id})
    await router._handle_message("wave3", linked, {"sender_id": "owner-sender", "content": f"approve {run_approval.id}"})
    assert linked.sent == ["✓ Approved: rollout"]
    assert await _status(db, run_approval.id) == "approved"
