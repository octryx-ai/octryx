"""Contract: session records belong to whoever may use their session, and STT is authenticated.

- orchestrator runs and clarification questions are readable by the session owner, a grant
  holder and an admin; another user gets 404 (the unknown-id answer) on every route, a ``read``
  grant holder gets 403 on every action;
- the cross-session clarification list is admin-only;
- ``/api/v1/stt`` refuses an anonymous caller and a non-member's Workspace before any provider is
  resolved.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Project, Role, Session, User, UserRole
from app.services.auth.tokens import create_access_token, hash_password
from app.services.session_access_service import grant_session_access


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


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def _session(db, owner: User) -> Session:
    session = Session(id=str(uuid.uuid4()), user_id=owner.id, agent_type="diagnosis", status="active", metadata_={})
    db.add(session)
    await db.commit()
    return session


@pytest.mark.asyncio
async def test_orchestrator_runs_are_scoped_to_their_session(client, db, auth_headers):
    owner, other, reader = await _user(db), await _user(db), await _user(db)
    session, others_session = await _session(db, owner), await _session(db, other)
    created = await client.post(
        "/api/v1/orchestrator", json={"session_id": session.id, "pattern_type": "parallel"}, headers=_auth(owner)
    )
    assert created.status_code == 200
    run_id = created.json()["id"]
    await grant_session_access(db, session_id=session.id, target_user_id=reader.id, scope="read")

    actions = [
        ("POST", "/api/v1/orchestrator/add-child", {"run_id": run_id, "child_session_id": session.id}),
        ("POST", "/api/v1/orchestrator/merge-child", {"run_id": run_id, "child_session_id": "c", "child_output": {}}),
        ("POST", "/api/v1/orchestrator/resolve-conflict", {"run_id": run_id, "conflict_key": "k", "resolution": {}}),
        ("POST", "/api/v1/orchestrator/submit-review", {"run_id": run_id, "score": "pass"}),
        ("POST", f"/api/v1/orchestrator/advance-step?run_id={run_id}", None),
        ("POST", "/api/v1/orchestrator/complete", {"run_id": run_id}),
        ("POST", f"/api/v1/orchestrator/{run_id}/cancel", None),
    ]
    reads = [("GET", f"/api/v1/orchestrator/{run_id}", None), ("GET", f"/api/v1/orchestrator?session_id={session.id}", None)]
    for method, path, body in reads + actions:
        refused = await client.request(method, path, json=body, headers=_auth(other))
        assert refused.status_code == 404, (path, refused.status_code)
    for method, path, body in actions:
        refused = await client.request(method, path, json=body, headers=_auth(reader))
        assert refused.status_code == 403, (path, refused.status_code)
    for method, path, body in reads:
        assert (await client.request(method, path, headers=_auth(reader))).status_code == 200
        assert (await client.request(method, path, headers=auth_headers)).status_code == 200

    # Nobody attaches a run, a parent or a child session they cannot see.
    for body in (
        {"session_id": others_session.id, "pattern_type": "parallel"},
        {"session_id": session.id, "parent_session_id": others_session.id, "pattern_type": "parallel"},
    ):
        assert (await client.post("/api/v1/orchestrator", json=body, headers=_auth(owner))).status_code == 404
    child = await client.post(
        "/api/v1/orchestrator/add-child",
        json={"run_id": run_id, "child_session_id": others_session.id},
        headers=_auth(owner),
    )
    assert child.status_code == 404
    project = (await db.execute(select(Project).limit(1))).scalar_one()
    foreign_project = await client.post(
        "/api/v1/orchestrator",
        json={"session_id": session.id, "project_id": project.id, "pattern_type": "parallel"},
        headers=_auth(owner),
    )
    # A Workspace the caller is no member of is refused before the session match like an unknown one (404); one of the
    # caller's own Workspaces that is not the session's is the mismatch (400).
    assert foreign_project.status_code == 404


@pytest.mark.asyncio
async def test_clarifications_are_scoped_to_their_session(client, db, auth_headers):
    owner, other, reader = await _user(db), await _user(db), await _user(db)
    session = await _session(db, owner)
    created = await client.post(
        "/api/v1/clarifications",
        json={"session_id": session.id, "question_id": "q1", "question_text": "Which region?"},
        headers=_auth(owner),
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
        refused = await client.request(method, path, json=body, headers=_auth(other))
        assert refused.status_code == 404, (path, refused.status_code)
    create_foreign = await client.post(
        "/api/v1/clarifications",
        json={"session_id": session.id, "question_id": "q2", "question_text": "Injected?"},
        headers=_auth(other),
    )
    assert create_foreign.status_code == 404
    for method, path, body in actions:
        assert (await client.request(method, path, json=body, headers=_auth(reader))).status_code == 403, path
    for method, path, _ in reads:
        assert (await client.request(method, path, headers=_auth(reader))).status_code == 200, path
    # The cross-session list is the admin tab's; a user lists one session they can see.
    assert (await client.get("/api/v1/clarifications", headers=_auth(owner))).status_code == 403
    assert (await client.get("/api/v1/clarifications", headers=auth_headers)).status_code == 200

    # No refused call changed the question: the owner still answers the open question.
    answered = await client.post(
        f"/api/v1/clarifications/{question_id}/answer", json={"answer_text": "eu"}, headers=_auth(owner)
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
        "/api/v1/stt/transcribe", files=audio, data={"project_id": project.id}, headers=_auth(user)
    )
    assert foreign.status_code == 404  # the answer of an unknown Workspace
    status = await client.get(f"/api/v1/stt/status?project_id={project.id}", headers=_auth(user))
    assert status.status_code == 404
    assert resolved == []
