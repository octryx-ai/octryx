"""Unmounted router tests: actual JWT actor, durable acceptance and post-commit start seam."""
from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.api.routes import workflow_handoffs as routes
from app.db import get_db
from app.models import Session, WorkflowRun
from app.models.runtime.workflow_handoff import WorkflowHandoff
from app.models.security.user import UserProject
from app.services.auth import create_access_token
from app.services.workflow_runs.handoff import inbox, service
from app.services.workflow_runs.handoff.contract import canonical_hash
from app.time_utils import utc_now
from tests.team_handoff_service_support import own_tables  # noqa: F401
from tests.team_handoff_support import action, allocate, counts, rights, setup_case

pytestmark = pytest.mark.asyncio
PREFIX = "/api/v1/workflow-handoffs"


def headers(actor):
    return {"Authorization": "Bearer " + create_access_token(actor.id)}


@pytest.fixture
async def api(db, monkeypatch):
    app = FastAPI()
    app.include_router(routes.router)  # Only this isolated test app; product http_setup remains root-owned.

    async def database():
        yield db

    async def started(db, binding):
        assert not db.in_transaction(), "child initialization must follow the acceptance commit"
        return {"state": "started", "child_run_id": binding["child_run_id"],
                "receiver_session_id": binding["receiver_session_id"]}

    app.dependency_overrides[get_db] = database
    monkeypatch.setattr(routes, "_rights", rights)
    monkeypatch.setattr(routes, "_allocate", allocate)
    monkeypatch.setattr(routes, "_start_child", started)
    monkeypatch.setattr(inbox, "_rights", rights)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_actual_principal_reads_only_approved_envelopes_without_sender_thread(api, db):
    c = await setup_case(db)
    before = await counts(db)
    result = await api.get(f"{PREFIX}/{c.row.id}", headers=headers(c.p))
    assert result.status_code == 200, result.text
    shown = result.json()["handoff"]
    assert shown["payload_hash"] == c.row.payload_hash
    assert shown["artefacts"]["definition_of_ready"]["decision_hash"] == c.decision.payload_hash
    assert "SENDER_ONLY_CANARY" not in result.text and "sender_transcript" not in result.text
    assert shown["scope"] == c.row.contract["scope"]
    assert await counts(db) == before


@pytest.mark.parametrize("actor", ["sender", "q", "outsider"])
async def test_unassigned_admin_and_other_users_have_generic_unknown_offer_denial(api, db, actor):
    c = await setup_case(db)
    user = getattr(c, actor)
    wrong = await api.get(f"{PREFIX}/{c.row.id}", headers=headers(user))
    unknown = await api.get(f"{PREFIX}/unknown", headers=headers(user))
    assert wrong.status_code == unknown.status_code == 404
    assert wrong.json() == unknown.json()
    refused = await api.post(f"{PREFIX}/{c.row.id}/actions", headers=headers(user), json=action(c.row))
    assert refused.status_code == 404
    assert c.row.child_run_id is None


async def test_accept_commits_before_start_once_and_remains_receiver_owned(api, db, monkeypatch):
    c = await setup_case(db, pool=True)
    before = await counts(db)
    offer_id, p_id, original = c.row.id, c.p.id, action(c.row)
    starts = []

    async def initialized(db, binding):
        assert not db.in_transaction()
        row = await db.get(WorkflowHandoff, offer_id, populate_existing=True)
        assert row.state == "accepted" and row.accepted_by == p_id
        starts.append(dict(binding))
        return {"state": "started", "child_run_id": binding["child_run_id"],
                "receiver_session_id": binding["receiver_session_id"]}

    monkeypatch.setattr(routes, "_start_child", initialized)
    result = await api.post(f"{PREFIX}/{offer_id}/actions", headers=headers(c.p), json=original)
    assert result.status_code == 200, result.text
    assert result.json()["continuation"]["state"] == "started"
    assert len(starts) == 1 and starts[0]["actor_id"] == p_id
    assert await counts(db) == tuple(n + 1 for n in before)
    child = await db.get(WorkflowRun, starts[0]["child_run_id"])
    session = await db.get(Session, starts[0]["receiver_session_id"])
    assert child.requested_by == session.user_id == p_id
    assert session.parent_session_id is None and "sender_transcript" not in child.context
    replay = await api.post(f"{PREFIX}/{offer_id}/actions", headers=headers(c.p), json=original)
    loser = await api.post(f"{PREFIX}/{offer_id}/actions", headers=headers(c.q), json=original)
    assert replay.status_code == loser.status_code == 409
    assert len(starts) == 1 and await counts(db) == tuple(n + 1 for n in before)


async def test_failed_postcommit_continuation_holds_without_reversing_acceptance_or_leaking_error(api, db, monkeypatch):
    c = await setup_case(db)
    offer_id, p_id = c.row.id, c.p.id
    before = await counts(db)

    async def cannot_start(db, binding):
        assert not db.in_transaction()
        raise RuntimeError("private internal runtime secret")

    monkeypatch.setattr(routes, "_start_child", cannot_start)
    result = await api.post(f"{PREFIX}/{offer_id}/actions", headers=headers(c.p), json=action(c.row))
    assert result.status_code == 200, result.text
    assert result.json()["continuation"]["state"] == "held"
    assert "private internal" not in result.text
    row = await db.get(WorkflowHandoff, offer_id, populate_existing=True)
    assert row.state == "accepted" and row.accepted_by == p_id
    assert await counts(db) == tuple(n + 1 for n in before)


@pytest.mark.parametrize("cause", ["hash", "round", "version", "expiry", "membership"])
async def test_stale_or_revoked_action_never_allocates_or_starts(api, db, monkeypatch, cause):
    c = await setup_case(db)
    original = action(c.row)
    p_headers = headers(c.p)
    before = await counts(db)
    if cause in {"hash", "round", "version"}:
        key = {"hash": "payload_hash", "round": "round", "version": "expected_state_version"}[cause]
        original[key] = "sha256:" + "0" * 64 if cause == "hash" else original[key] + 1
    elif cause == "expiry":
        c.row.expires_at = utc_now() - timedelta(seconds=1)
        c.row.payload_hash = canonical_hash(service.binding_payload(c.row))
        original = action(c.row)
    else:
        await db.execute(delete(UserProject).where(UserProject.user_id == c.p.id,
                                                   UserProject.project_id == c.parent.project_id))
    await db.flush()

    async def never(*args, **kwargs):
        raise AssertionError("refused offers must not start")

    monkeypatch.setattr(routes, "_start_child", never)
    result = await api.post(f"{PREFIX}/{c.row.id}/actions", headers=p_headers, json=original)
    assert result.status_code == (404 if cause == "membership" else 409), result.text
    assert await counts(db) == before


async def test_authentication_and_closed_action_body_do_not_take_a_user_argument(api, db):
    c = await setup_case(db)
    unauthenticated = await api.get(f"{PREFIX}/{c.row.id}")
    assert unauthenticated.status_code == 401
    spoof = await api.post(f"{PREFIX}/{c.row.id}/actions", headers=headers(c.q),
                           json={**action(c.row), "actor_id": c.p.id})
    assert spoof.status_code == 422
    assert c.row.child_run_id is None


async def test_personal_decline_disappears_only_for_that_candidate(api, db):
    c = await setup_case(db, pool=True)
    decline = await api.post(f"{PREFIX}/{c.row.id}/actions", headers=headers(c.p), json=action(c.row, "decline"))
    assert decline.status_code == 200, decline.text
    assert decline.json()["handoff"]["personal_response"] == "declined"
    assert await inbox.inbox_items(db, c.p) == []
    other = await inbox.inbox_items(db, c.q)
    assert len(other) == 1 and other[0]["handoff_action"] == {"handoff_id": c.row.id}
    assert c.row.state == "offered" and c.row.child_run_id is None


async def test_inbox_excludes_unassigned_admin_expired_unreadable_or_revoked_offers(api, db, monkeypatch):
    c = await setup_case(db)
    assert await inbox.inbox_items(db, c.sender) == []
    assert await inbox.inbox_items(db, c.outsider) == []
    shown = await inbox.inbox_items(db, c.p)
    assert len(shown) == 1 and "SENDER_ONLY_CANARY" not in json.dumps(shown)
    assert "href" not in shown[0]["link"]

    async def unreadable(**kwargs):
        return {"allowed": False}

    monkeypatch.setattr(inbox, "_rights", unreadable)
    assert await inbox.inbox_items(db, c.p) == []
    monkeypatch.setattr(inbox, "_rights", rights)
    c.row.expires_at = utc_now() - timedelta(seconds=1)
    await db.flush()
    assert await inbox.inbox_items(db, c.p) == []
