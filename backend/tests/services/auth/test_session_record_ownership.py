"""Contract: session records belong to whoever may use their session, and STT is authenticated."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Project, Role, Session, User, UserRole
from app.services.auth.tokens import hash_password
from app.services.session_access_service import grant_session_access
from tests.policy_engine_support import bearer


async def _user(db) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=str(uuid.uuid4()),
        username=f"owner-test-{suffix}",
        email=f"owner-test-{suffix}@example.com",
        password_hash=hash_password("owner-Test-Pw-123"),
        display_name="owner test",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    role = (await db.execute(select(Role).where(Role.name == "viewer"))).scalar_one()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    await db.commit()
    return user


async def _session(db, owner: User) -> Session:
    session = Session(id=str(uuid.uuid4()), user_id=owner.id, agent_type="diagnosis", status="active", metadata_={})
    db.add(session)
    await db.commit()
    return session




@pytest.mark.asyncio
async def test_clarifications_are_scoped_to_their_session(client, db, auth_headers):
    owner, other, reader = await _user(db), await _user(db), await _user(db)
    session = await _session(db, owner)
    created = await client.post(
        "/api/v1/clarifications",
        json={"session_id": session.id, "question_id": "q1", "question_text": "Which region?"},
        headers=bearer(owner.id),
    )
    assert created.status_code == 200
    question_id = created.json()["id"]
    await grant_session_access(db, session_id=session.id, target_user_id=reader.id, scope="read")

    actions = [
        ("POST", f"/api/v1/clarifications/{question_id}/answer", {"answer_text": "eu"}),
        ("POST", f"/api/v1/clarifications/{question_id}/skip", {}),
        ("POST", f"/api/v1/clarifications/{question_id}/cancel", None),
    ]
    reads = [
        ("GET", f"/api/v1/clarifications/{question_id}", None),
        ("GET", f"/api/v1/clarifications?session_id={session.id}", None),
        ("GET", f"/api/v1/clarifications/session/{session.id}/open", None),
    ]
    for method, path, body in reads + actions:
        refused = await client.request(method, path, json=body, headers=bearer(other.id))
        assert refused.status_code == 404, (path, refused.status_code)
    create_foreign = await client.post(
        "/api/v1/clarifications",
        json={"session_id": session.id, "question_id": "q2", "question_text": "Injected?"},
        headers=bearer(other.id),
    )
    assert create_foreign.status_code == 404
    for method, path, body in actions:
        assert (await client.request(method, path, json=body, headers=bearer(reader.id))).status_code == 403, path
    for method, path, _ in reads:
        assert (await client.request(method, path, headers=bearer(reader.id))).status_code == 200, path
    assert (await client.get("/api/v1/clarifications", headers=bearer(owner.id))).status_code == 403
    assert (await client.get("/api/v1/clarifications", headers=auth_headers)).status_code == 200

    answered = await client.post(
        f"/api/v1/clarifications/{question_id}/answer", json={"answer_text": "eu"}, headers=bearer(owner.id)
    )
    assert answered.status_code == 200
    assert answered.json()["answered_by"] == owner.id


@pytest.mark.asyncio
async def test_stt_refuses_anonymous_callers_and_foreign_workspaces_before_any_provider(client, db, monkeypatch):
    resolved = []

    async def _resolve(db, *, project_id=None):
        resolved.append(project_id)
        raise AssertionError("the provider must not be resolved for a refused caller")

    monkeypatch.setattr("app.services.stt.resolve_stt_service", _resolve)
    audio = {"audio": ("recording.webm", b"audio-bytes", "audio/webm")}
    assert (await client.post("/api/v1/stt/transcribe", files=audio)).status_code == 401
    assert (await client.get("/api/v1/stt/status")).status_code == 401

    user = await _user(db)
    project = (await db.execute(select(Project).limit(1))).scalar_one()
    foreign = await client.post(
        "/api/v1/stt/transcribe", files=audio, data={"project_id": project.id}, headers=bearer(user.id)
    )
    assert foreign.status_code == 404
    status = await client.get(f"/api/v1/stt/status?project_id={project.id}", headers=bearer(user.id))
    assert status.status_code == 404
    assert resolved == []
