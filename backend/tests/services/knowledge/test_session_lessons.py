"""Session lessons for the team: off by default, own Workspace, secrets out, proposed until confirmed by the role with
the right, limits and idempotency, rejection deletes and audits."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AuditLog, KnowledgeMemoryItem
from app.models.project.knowledge_memory import MemoryState
from app.services.knowledge.memory import session_lessons as sl
from app.services.knowledge.memory.settings import set_memory_policy
from app.services.knowledge.memory.visibility import recallable
from app.time_utils import utc_now
from tests.services.agent_gateway.test_agent_gateway_control_plane import BASE, _gateway, _workspace

AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
PRIVATE_KEY = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAx\n-----END RSA PRIVATE KEY-----"


class _Model:
    def __init__(self, lessons):
        self.lessons, self.seen = lessons, []

    async def json(self, *, system, user):
        self.seen.append(user)
        return {"lessons": self.lessons}


def _factory(model):
    async def make(db, *, project_id):
        return model
    return make


FACTS = {"goal": "Make gradle tests pass in the VPN", "requests": ["fix the build"], "files": ["/repo/build.gradle"],
         "tests": [{"command": "./gradlew test --offline", "passed": True}]}


@pytest.mark.asyncio
async def test_off_by_default_and_on_it_proposes_lessons_that_are_never_recalled(db):
    project = await _workspace(db)
    _, session = await _gateway(db, project)
    model = _Model([{"class": "learning", "text": "Gradle tests in the VPN need --offline; the proxy blocks Maven."}])
    off = await sl.capture_session_lessons(db, user_id=session.user_id, workspace_id=project.id,
                                           session_id=session.id, ref="ref-0001", facts=FACTS, summary="s",
                                           model_factory=_factory(model))
    assert off == {"state": "off"} and model.seen == []

    await set_memory_policy(db, project.id, session_lessons=True)
    result = await sl.capture_session_lessons(db, user_id=session.user_id, workspace_id=project.id,
                                              session_id=session.id, ref="ref-0001", facts=FACTS,
                                              summary=f"key {AWS_KEY}\n{PRIVATE_KEY}", model_factory=_factory(model))
    assert result["state"] == "captured" and result["proposed"] == 1
    assert AWS_KEY not in model.seen[0] and "PRIVATE KEY" not in model.seen[0] and "[redacted]" in model.seen[0]
    [item] = (await db.execute(select(KnowledgeMemoryItem).where(KnowledgeMemoryItem.project_id == project.id,
                                                                 KnowledgeMemoryItem.turn_ref == "lessons:ref-0001"))
              ).scalars().all()
    assert item.state == MemoryState.PROPOSED.value and item.scope == "workspace"
    recalled = (await db.execute(select(KnowledgeMemoryItem.id).where(recallable(utc_now())))).scalars().all()
    assert item.id not in recalled

    again = await sl.capture_session_lessons(db, user_id=session.user_id, workspace_id=project.id,
                                             session_id=session.id, ref="ref-0001", facts=FACTS, summary="s",
                                             model_factory=_factory(model))
    assert again == {"state": "duplicate"} and len(model.seen) == 1


@pytest.mark.asyncio
async def test_secret_or_duplicate_candidates_are_dropped_and_limits_hold(db, monkeypatch):
    project = await _workspace(db)
    _, session = await _gateway(db, project)
    await set_memory_policy(db, project.id, session_lessons=True)
    model = _Model([
        {"class": "convention", "text": "Feature branches are named feat/<ticket>-<slug>."},
        {"class": "convention", "text": "Feature branches are named feat/<ticket>-<slug>."},
        {"class": "learning", "text": f"Use the deploy key {PRIVATE_KEY}"},
        {"class": "personal", "text": "I like dark mode"},
        {"class": "decision", "text": "A fourth candidate is cut by the limit of three."},
    ])
    result = await sl.capture_session_lessons(db, user_id=session.user_id, workspace_id=project.id,
                                              session_id=session.id, ref="ref-0002", facts=FACTS, summary=None,
                                              model_factory=_factory(model))
    assert result["proposed"] == 1
    monkeypatch.setattr(sl, "MAX_PER_SESSION_DAY", 1)
    limited = await sl.capture_session_lessons(db, user_id=session.user_id, workspace_id=project.id,
                                               session_id=session.id, ref="ref-0003", facts=FACTS, summary="x",
                                               model_factory=_factory(model))
    assert limited == {"state": "limited"}
    assert (await sl.capture_session_lessons(db, user_id=session.user_id, workspace_id=project.id,
                                             session_id=session.id, ref="x", facts=FACTS, summary="x",
                                             model_factory=_factory(model)))["reason"] == "ref_invalid"


@pytest.mark.asyncio
async def test_the_gateway_endpoint_uses_the_sessions_own_workspace(client, db, monkeypatch):
    project = await _workspace(db)
    headers, session = await _gateway(db, project)
    await set_memory_policy(db, project.id, session_lessons=True)
    await db.commit()
    model = _Model([{"class": "decision", "text": "We pin Python to 3.12 in every service image."}])
    monkeypatch.setattr(sl, "governed_capture_model", _factory(model))
    response = await client.post(f"{BASE}/sessions/lessons", headers=headers,
                                 json={"ref": "ref-endpoint", "facts": FACTS, "summary": "done",
                                       "workspace_id": "some-other-workspace"})
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "captured"
    [item] = (await db.execute(select(KnowledgeMemoryItem).where(
        KnowledgeMemoryItem.turn_ref == "lessons:ref-endpoint"))).scalars().all()
    assert item.project_id == project.id


@pytest.mark.asyncio
async def test_confirm_right_by_role_reject_deletes_and_audits(client, db, auth_headers):
    project = await _workspace(db)
    _, session = await _gateway(db, project)
    await set_memory_policy(db, project.id, session_lessons=True)
    model = _Model([{"class": "learning", "text": "Run alembic heads before every migration PR; one head only."},
                    {"class": "convention", "text": "Work packages live in docs/work-packages."}])
    await sl.capture_session_lessons(db, user_id=session.user_id, workspace_id=project.id, session_id=session.id,
                                     ref="ref-confirm", facts=FACTS, summary="s", model_factory=_factory(model))
    await db.commit()
    route = f"/api/v1/workspaces/{project.id}/knowledge/memory"
    listing = (await client.get(route, headers=auth_headers)).json()
    proposed = [item for item in listing["items"] if item.get("state") == "proposed"]
    assert len(proposed) == 2 and all(item.get("may_change") for item in proposed)
    assert listing["confirm_roles"] == ["owner", "admin"] and listing["session_lessons"] is True

    confirmed = await client.post(f"{route}/{proposed[0]['id']}/confirm", headers=auth_headers)
    assert confirmed.status_code == 200, confirmed.text
    rejected = await client.post(f"{route}/{proposed[1]['id']}/reject", headers=auth_headers)
    assert rejected.status_code == 200, rejected.text
    assert await db.get(KnowledgeMemoryItem, proposed[1]["id"]) is None
    actions = (await db.execute(select(AuditLog.action).where(
        AuditLog.resource_id.in_([proposed[0]["id"], proposed[1]["id"]])))).scalars().all()
    assert sorted(actions) == ["knowledge_memory.lesson_confirmed", "knowledge_memory.lesson_rejected"]

    narrowed = await client.put(f"{route}/settings", headers=auth_headers, json={"confirm_roles": ["admin"]})
    assert narrowed.status_code == 200 and narrowed.json()["confirm_roles"] == ["admin"]
    bad = await client.put(f"{route}/settings", headers=auth_headers, json={"confirm_roles": ["root"]})
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_one_call_never_goes_beyond_the_days_allowance(db, monkeypatch):
    project = await _workspace(db)
    _, session = await _gateway(db, project)
    await set_memory_policy(db, project.id, session_lessons=True)
    monkeypatch.setattr(sl, "MAX_PER_SESSION_DAY", 1)
    model = _Model([{"class": "learning", "text": "Lesson one is long enough to be stored as a memory."},
                    {"class": "learning", "text": "Lesson two is long enough to be stored as a memory."},
                    {"class": "learning", "text": "Lesson three is long enough to be stored as a memory."}])
    result = await sl.capture_session_lessons(db, user_id=session.user_id, workspace_id=project.id,
                                              session_id=session.id, ref="ref-cap1", facts=FACTS, summary="s",
                                              model_factory=_factory(model))
    assert result["proposed"] == 1 and result["skipped"] == 2
