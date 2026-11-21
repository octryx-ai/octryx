"""The answer route checks role and scope before the service, accepts no model fields and is served under secure work."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.routes import secure_work_plan_answers as answer_routes
from app.db import get_db
from app.models import Project, Role, User, UserProject, UserRole
from app.services.auth.tokens import create_access_token, hash_password
from tests.secure_work_plan_clarification_answers_support import _admin, _answers, _item, _plan

# --- route -----------------------------------------------------------------------------------------


async def _operator(db, *, operator=True) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(username=f"answer-{suffix}", email=f"answer-{suffix}@example.test",
                password_hash=hash_password("Answer-Pw-123"), is_active=True)
    db.add(user)
    await db.flush()
    if operator:
        role = (await db.execute(select(Role).where(Role.name == "operator"))).scalar_one_or_none()
        if role is None:
            role = Role(name="operator")
            db.add(role)
            await db.flush()
        db.add(UserRole(user_id=user.id, role_id=role.id))
    return user


@pytest.fixture
async def answer_client(db):
    local = FastAPI()
    local.include_router(answer_routes.router, prefix="/api/v1/secure-work")

    async def override_get_db():
        yield db

    local.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=local), base_url="http://test") as client:
        yield client


async def test_route_checks_role_and_scope_before_the_service_and_accepts_no_model_fields(db, answer_client,
                                                                                          monkeypatch):
    admin = await _admin(db)
    own, foreign = Project(name=f"Answer Own {uuid.uuid4().hex[:6]}"), Project(name=f"Answer Foreign {uuid.uuid4().hex[:6]}")
    db.add_all([own, foreign])
    await db.flush()
    member, plain = await _operator(db), await _operator(db, operator=False)
    db.add_all([UserProject(user_id=member.id, project_id=own.id), UserProject(user_id=plain.id, project_id=own.id)])
    own_plan = await _plan(db, await _item(db, project_id=own.id), admin, version=1)
    foreign_plan = await _plan(db, await _item(db, project_id=foreign.id), admin, version=1)
    seen: list[dict] = []

    async def service_probe(_db, **kwargs):
        seen.append(kwargs)
        return {"id": "new-plan", "version": 2}

    monkeypatch.setattr(answer_routes, "answer_plan_clarifications", service_probe)
    body = {"expected_latest_version": 1, "answers": _answers((0, "Staging."))}

    def url(plan_id):
        return f"/api/v1/secure-work/change-plans/{plan_id}/clarification-answers"

    def auth(user):
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}

    assert (await answer_client.post(url(own_plan.id), json=body, headers=auth(plain))).status_code == 403
    assert (await answer_client.post(url(foreign_plan.id), json=body, headers=auth(member))).status_code == 404
    assert (await answer_client.post(url(str(uuid.uuid4())), json=body, headers=auth(member))).status_code == 404
    for extra in ({"max_tokens": 64000}, {"workflow_id": "foreign"}, {"runtime_target_id": "r"}):
        assert (await answer_client.post(url(own_plan.id), json={**body, **extra}, headers=auth(member))).status_code == 422
    assert seen == []

    accepted = await answer_client.post(url(own_plan.id), json=body, headers=auth(member))
    assert accepted.status_code == 200, accepted.text
    assert seen[0]["change_plan_id"] == own_plan.id and seen[0]["expected_latest_version"] == 1
    assert seen[0]["answers"] == _answers((0, "Staging."))


def test_the_application_serves_the_answer_route_under_secure_work():
    from app.main import app

    paths = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}
    assert ("/api/v1/secure-work/change-plans/{change_plan_id}/clarification-answers", "POST") in paths
