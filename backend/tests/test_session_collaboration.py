"""Session collaborators and the handover flow."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Notification, Role, Session, SessionCollaborator, SessionHandover, User, UserRole
from app.services.auth import hash_password
from tests.conftest import ADMIN_PASSWORD


async def _seed_viewer_collaborator(db) -> User:
    viewer_role = (await db.execute(select(Role).where(Role.name == "viewer"))).scalar_one()
    collaborator = User(
        id=str(uuid.uuid4()),
        username="collab-user",
        email="collab@example.com",
        password_hash=hash_password("secret123"),
        display_name="Collab User",
        is_active=True,
    )
    db.add(collaborator)
    await db.flush()
    db.add(UserRole(user_id=collaborator.id, role_id=viewer_role.id))
    await db.commit()
    return collaborator


async def _assert_observer_can_read_but_not_write(client, session_id: str, collab_headers: dict) -> None:
    list_resp = await client.get("/api/v1/sessions", headers=collab_headers)
    assert list_resp.status_code == 200
    assert any(item["id"] == session_id and item["access_role"] == "observer" for item in list_resp.json())

    read_resp = await client.get(f"/api/v1/sessions/{session_id}", headers=collab_headers)
    assert read_resp.status_code == 200

    blocked_post = await client.post(
        f"/api/v1/sessions/{session_id}/messages",
        headers=collab_headers,
        json={"content": "observer cannot write"},
    )
    assert blocked_post.status_code == 403


async def _notifications_for(db, user_id: str) -> list[Notification]:
    return (
        (
            await db.execute(
                select(Notification)
                .where(Notification.user_id == user_id)
                .order_by(Notification.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def _assert_handover_accepted(db, session_id: str, *, new_owner_id: str, old_owner_id: str, handover_id: str):
    session = await db.get(Session, session_id)
    assert session is not None
    assert session.user_id == new_owner_id
    old_owner_collab = await db.get(SessionCollaborator, {"session_id": session_id, "user_id": old_owner_id})
    assert old_owner_collab is not None
    assert old_owner_collab.role == "contributor"
    handover = await db.get(SessionHandover, handover_id)
    assert handover is not None
    assert handover.status == "accepted"


@pytest.mark.asyncio
async def test_session_collaborator_and_handover_flow(client, db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    collaborator = await _seed_viewer_collaborator(db)

    admin_auth = await client.post("/api/v1/auth/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert admin_auth.status_code == 200
    admin_headers = {"Authorization": f"Bearer {admin_auth.json()['access_token']}"}

    collab_auth = await client.post("/api/v1/auth/login", data={"username": "collab-user", "password": "secret123"})
    assert collab_auth.status_code == 200
    collab_headers = {"Authorization": f"Bearer {collab_auth.json()['access_token']}"}

    create_session_resp = await client.post("/api/v1/sessions", headers=admin_headers, json={"agent_type": "diagnosis"})
    assert create_session_resp.status_code == 200
    session_id = create_session_resp.json()["id"]

    share_resp = await client.post(
        f"/api/v1/sessions/{session_id}/collaborators",
        headers=admin_headers,
        json={"user_id": collaborator.id, "role": "observer"},
    )
    assert share_resp.status_code == 200, share_resp.text
    assert share_resp.json()["role"] == "observer"

    await _assert_observer_can_read_but_not_write(client, session_id, collab_headers)

    promote_resp = await client.post(
        f"/api/v1/sessions/{session_id}/collaborators",
        headers=admin_headers,
        json={"user_id": collaborator.id, "role": "contributor"},
    )
    assert promote_resp.status_code == 200
    assert promote_resp.json()["role"] == "contributor"

    handover_resp = await client.post(
        f"/api/v1/sessions/{session_id}/handovers",
        headers=admin_headers,
        json={
            "to_user_id": collaborator.id,
            "reason": "Please continue this incident",
            "context_summary": "Payment timeout already triaged",
        },
    )
    assert handover_resp.status_code == 200, handover_resp.text
    handover_id = handover_resp.json()["id"]

    notifications = await _notifications_for(db, collaborator.id)
    assert any(row.type == "session.handover_requested" for row in notifications)

    accept_resp = await client.post(
        f"/api/v1/sessions/handovers/{handover_id}/respond",
        headers=collab_headers,
        json={"action": "accept"},
    )
    assert accept_resp.status_code == 200
    assert accept_resp.json()["status"] == "accepted"

    await _assert_handover_accepted(
        db, session_id, new_owner_id=collaborator.id, old_owner_id=admin.id, handover_id=handover_id
    )
