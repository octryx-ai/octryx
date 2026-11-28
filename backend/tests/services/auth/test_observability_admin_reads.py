"""Admin-only audit/usage reads and append-only run history across a chat re-run."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.middleware.security.rate_limit import clear_rate_limit_buckets
from app.models import (
    Approval,
    ChangePreview,
    Message,
    Role,
    Session,
    TurnTrace,
    UsageEvent,
    User,
    UserRole,
)
from app.services.auth.tokens import create_access_token, hash_password
from app.services.auth_rate_limit import clear_all_auth_rate_limits
from app.services.chat_rerun import prepare_chat_rerun
from app.time_utils import utc_now

PLATFORM_WIDE_READS = ("/api/v1/audit", "/api/v1/usage")


async def _user_with_role(db, role_name: str) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=str(uuid.uuid4()),
        username=f"{role_name}-{suffix}",
        email=f"{role_name}-{suffix}@example.com",
        password_hash=hash_password("o0-Test-Pw-123"),
        display_name=role_name,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    role = (await db.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    await db.commit()
    return user


async def _get(client, path: str, user: User):
    clear_rate_limit_buckets()
    clear_all_auth_rate_limits()
    client.cookies.clear()
    return await client.get(path, headers={"Authorization": f"Bearer {create_access_token(user.id)}"})


@pytest.mark.asyncio
@pytest.mark.parametrize("role_name", ["viewer", "technical", "operator"])
async def test_platform_wide_audit_and_usage_reads_refuse_non_admins(client, db, role_name):
    member = await _user_with_role(db, role_name)
    for path in PLATFORM_WIDE_READS:
        response = await _get(client, path, member)
        assert response.status_code == 403, (path, response.status_code)


@pytest.mark.asyncio
async def test_platform_wide_audit_and_usage_reads_serve_the_admin(client, db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    audit = await _get(client, "/api/v1/audit", admin)
    usage = await _get(client, "/api/v1/usage", admin)
    assert audit.status_code == 200 and isinstance(audit.json(), list)
    assert usage.status_code == 200 and "total_cost" in usage.json()


@pytest.mark.asyncio
async def test_chat_rerun_keeps_approvals_usage_and_traces(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    now = utc_now()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, metadata_={})
    target = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="user",
        content="Original",
        created_at=now - timedelta(minutes=2),
    )
    later = Message(id=str(uuid.uuid4()), session_id=session.id, role="assistant", content="Old answer", created_at=now)
    db.add_all([session, target, later])
    await db.flush()
    pending = Approval(
        id=str(uuid.uuid4()),
        session_id=session.id,
        requested_by=admin.id,
        action="shell",
        status="pending",
        created_at=now,
    )
    decided = Approval(
        id=str(uuid.uuid4()),
        session_id=session.id,
        requested_by=admin.id,
        action="write",
        status="approved",
        created_at=now,
    )
    db.add_all([pending, decided])
    await db.flush()
    preview = ChangePreview(
        id=str(uuid.uuid4()),
        session_id=session.id,
        approval_id=decided.id,
        tool_name="write",
        preview_json="{}",
        created_at=now,
    )
    trace = TurnTrace(id=str(uuid.uuid4()), session_id=session.id, message_id=later.id, created_at=now)
    usage = UsageEvent(
        id=str(uuid.uuid4()), session_id=session.id, user_id=admin.id, model="m", tokens_in=10, cost=0.5, created_at=now
    )
    db.add_all([preview, trace, usage])
    await db.commit()

    await prepare_chat_rerun(db, session=session, target_message=target, prompt="Edited")

    db.expunge_all()
    assert await db.get(Message, later.id) is None
    pending_after = await db.get(Approval, pending.id)
    decided_after = await db.get(Approval, decided.id)
    assert pending_after is not None and pending_after.status == "cancelled"
    assert pending_after.resolved_at is not None and "re-run" in pending_after.decision_note
    assert decided_after is not None and decided_after.status == "approved"
    assert await db.get(ChangePreview, preview.id) is not None
    trace_after = await db.get(TurnTrace, trace.id)
    assert trace_after is not None and trace_after.message_id is None
    assert trace_after.context_snapshot_json["superseded"]["message_id"] == later.id
    usage_after = await db.get(UsageEvent, usage.id)
    assert usage_after is not None and float(usage_after.cost) == 0.5
