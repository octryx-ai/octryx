"""Seat session hardening: clear keeps the session, identity is rechecked per call, header and upstream validation, and the RLS middleware never decodes the subscription bearer."""

# ruff: noqa: F811  (the shared ``anthropic`` fixture is imported, then requested by name)
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AgentPresence, OAuthGrant, User
from app.time_utils import utc_now
from tests.agent_gateway.seat_presence_support import (
    FINALIZE,
    SEAT,
    _body,
    _gateway_headers,
    _register,
    _seat_headers,
    _seat_session,
    _workspace,
)
from tests.agent_gateway.seat_upstream_support import anthropic  # noqa: F401 - fixture
from tests.knowledge_evidence_seed_support import seed_member


@pytest.mark.committed_db  # own DB session per request: the seat call's background work never shares one
@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["seat", "governed"])
async def test_clear_keeps_the_session_alive_for_both_profiles(client, db, anthropic, profile):
    if profile == "seat":
        workspace_id, _user, gateway, credential = await _seat_session(client, db)
    else:
        workspace_id = await _workspace(db)
        user_id = await seed_member(db, workspace_id=workspace_id, role="member")
        await db.commit()
        gateway = await _gateway_headers(db, user_id, workspace_id)
        assert (await _register(client, gateway, profile="governed")).status_code == 200

    kept = await client.post(FINALIZE, json={"end_reason": "clear", "summary": "cleared"}, headers=gateway)

    row = (await db.execute(select(AgentPresence).where(AgentPresence.project_id == workspace_id))).scalar_one()
    await db.refresh(row)
    assert kept.json() == {"state": "kept_alive", "reason": "clear"}
    assert (row.state, row.stopped_at) == ("active", None)
    if profile == "seat":
        assert row.seat_credential_hash is not None
        assert (await client.post(SEAT, json=_body(), headers=_seat_headers(gateway, credential))).status_code == 200
    ended = await client.post(FINALIZE, json={"end_reason": "logout", "summary": "done"}, headers=gateway)
    await db.refresh(row)
    assert ended.json()["state"] == "finalized" and row.state == "stopped" and row.seat_credential_hash is None


@pytest.mark.asyncio
@pytest.mark.parametrize("check", ["membership", "grant_revoked", "workspace_header", "user_inactive"])
async def test_every_seat_call_rechecks_identity(client, db, anthropic, check):
    from app.models.security.user import UserProject

    workspace_id, user_id, gateway, credential = await _seat_session(client, db)
    headers = _seat_headers(gateway, credential)
    row = (await db.execute(select(AgentPresence).where(AgentPresence.project_id == workspace_id))).scalar_one()
    if check == "membership":
        membership = (await db.execute(select(UserProject).where(
            UserProject.user_id == user_id, UserProject.project_id == workspace_id))).scalar_one()
        await db.delete(membership)
        expected = (403, "workspace_not_authorized")
    elif check == "grant_revoked":
        (await db.get(OAuthGrant, row.seat_grant_id)).revoked_at = utc_now()
        expected = (401, "seat_grant_revoked")
    elif check == "workspace_header":
        headers["x-octryx-workspace"] = await _workspace(db)
        expected = (403, "workspace_not_authorized")
    else:
        (await db.get(User, user_id)).is_active = False
        expected = (401, "gateway_user_inactive")
    await db.commit()

    refused = await client.post(SEAT, json=_body(), headers=headers)

    assert (refused.status_code, expected[1] in refused.json()["error"]["message"]) == (expected[0], True)
    assert anthropic.requests == []


@pytest.mark.asyncio
async def test_a_non_ascii_header_is_a_coded_400_never_a_500(client, db, anthropic):
    _workspace_id, _user, gateway, credential = await _seat_session(client, db)
    headers = {**_seat_headers(gateway, credential), "authorization": "Bearer sk-ant-oat01-éé"}

    response = await client.post(SEAT, json=_body(), headers={k: v.encode("latin-1") for k, v in headers.items()})

    assert response.status_code == 400 and "request_header_invalid" in response.json()["error"]["message"]
    assert anthropic.requests == []


def test_the_seat_upstream_must_be_https_or_loopback_http():
    from app.services.model_gateway.inbound.seat_upstream import seat_upstream_base_url, seat_upstream_problem

    assert (seat_upstream_base_url({}), seat_upstream_problem({})) == ("https://api.anthropic.com", "")
    assert seat_upstream_problem({"ANTHROPIC_SEAT_UPSTREAM": "https://anthropic.example"}) == ""
    assert seat_upstream_base_url({"ANTHROPIC_SEAT_UPSTREAM": "http://127.0.0.1:9000"}) == "http://127.0.0.1:9000"
    for good in ("http://localhost:8080", "http://[::1]:9000", "http://127.8.9.10"):
        assert seat_upstream_problem({"ANTHROPIC_SEAT_UPSTREAM": good}) == "", good
    for bad in ("http://10.0.0.1", "http://api.anthropic.com", "https://u:p@evil", "file:///etc", "ftp://x",
                "http://127.0.0.1.evil.example", "http://127.evil.example", "http://localhost.evil.example",
                "http://0.0.0.0"):
        assert seat_upstream_problem({"ANTHROPIC_SEAT_UPSTREAM": bad}) == "seat_upstream_misconfigured", bad
        assert seat_upstream_base_url({"ANTHROPIC_SEAT_UPSTREAM": bad}) == "https://api.anthropic.com", bad


@pytest.mark.asyncio
async def test_a_misconfigured_upstream_refuses_seat_calls(client, db, anthropic, monkeypatch):
    _workspace_id, _user, gateway, credential = await _seat_session(client, db)
    monkeypatch.setenv("ANTHROPIC_SEAT_UPSTREAM", "http://10.0.0.1")

    refused = await client.post(SEAT, json=_body(), headers=_seat_headers(gateway, credential))

    assert refused.status_code == 503 and "seat_upstream_misconfigured" in refused.json()["error"]["message"]
    assert anthropic.requests == []
