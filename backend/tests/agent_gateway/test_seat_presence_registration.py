"""Seat and governed session registration: policy and classification refusals, the hashed seat credential, the strict workspace assistant and the kept needs-auth mark."""

# ruff: noqa: F811  (the shared ``anthropic`` fixture is imported, then requested by name)
from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import AgentPresence
from app.services.agent_gateway.policy_keys import AgentGatewayPolicyError
from app.services.agent_gateway.policy_normalize import normalize_agent_gateway_policy
from tests.agent_gateway.seat_presence_support import (
    POLICY,
    REGISTER,
    SEAT_POLICY,
    _bearer,
    _body,
    _found_anywhere,
    _gateway_headers,
    _register,
    _seat_session,
    _workspace,
)
from tests.knowledge_evidence_seed_support import seed_member

# --- policy and registration ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("classification", "policy", "reason"), [
    ("confidential", None, "seat_classification_too_sensitive"),  # unset: open up to internal
    ("internal", {"seat_mode": "forbidden"}, "seat_mode_forbidden"),
    ("internal", {"seat_mode": "allowed", "requires_governed_routing": True}, "seat_requires_governed_routing"),
    ("confidential", SEAT_POLICY, "seat_classification_too_sensitive"),
    ("restricted", SEAT_POLICY, "seat_classification_too_sensitive"),
    ("secret", SEAT_POLICY, "seat_classification_too_sensitive"),
    (None, SEAT_POLICY, "seat_classification_unresolved"),
])
async def test_seat_registration_is_refused_by_policy_and_classification(client, db, classification, policy, reason):
    workspace_id = await _workspace(db, classification=classification, policy=policy)
    user_id = await seed_member(db, workspace_id=workspace_id, role="member")
    await db.commit()
    gateway = await _gateway_headers(db, user_id, workspace_id)

    refused = await _register(client, gateway)
    seen = (await client.get(POLICY, headers=gateway)).json()

    assert (refused.status_code, refused.json()["reason"]) == (403, reason)
    assert seen["seat"] == {"seat_mode": "forbidden", "reason": reason}
    assert (await db.execute(select(AgentPresence).where(AgentPresence.project_id == workspace_id))).first() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("classification", ["public", "internal"])
async def test_a_seat_registration_returns_a_credential_stored_only_as_its_hash(client, db, classification):
    workspace_id, _user, gateway, credential = await _seat_session(client, db, classification=classification)

    row = (await db.execute(select(AgentPresence).where(AgentPresence.project_id == workspace_id))).scalar_one()
    assert len(credential) >= 43 and row.seat_credential_hash == hashlib.sha256(credential.encode()).hexdigest()
    assert row.profile == "seat" and row.branch == "feature/brd-6" and row.state == "active"
    assert timedelta(hours=11) < row.seat_credential_expires_at - row.registered_at <= timedelta(hours=12)
    assert await _found_anywhere(db, credential) == []
    again = await _register(client, gateway)
    assert (again.status_code, again.json()["reason"]) == (409, "session_already_registered")


@pytest.mark.asyncio
async def test_a_governed_registration_gives_presence_without_a_credential(client, db):
    workspace_id = await _workspace(db, classification="confidential")
    user_id = await seed_member(db, workspace_id=workspace_id, role="member")
    await db.commit()

    answer = await _register(client, await _gateway_headers(db, user_id, workspace_id), profile="governed")

    body = answer.json()
    # Outside a run the session follows the permission mode; no read-only Assistant instructions
    # unless the Workspace keeps sessions read-only (test_a_strict_workspace_still_gets_the_read_only_assistant).
    assert "platform_agent" not in body
    assert answer.status_code == 200 and body == {"state": "registered", "profile": "governed"}
    row = (await db.execute(select(AgentPresence).where(AgentPresence.project_id == workspace_id))).scalar_one()
    assert (row.profile, row.seat_credential_hash) == ("governed", None)


def test_the_seat_policy_keys_are_validated():
    assert normalize_agent_gateway_policy({"seat_mode": "allowed", "seat_models": ["claude-opus-5-5"]}) == {
        "seat_mode": "allowed", "seat_models": ["claude-opus-5-5"]}
    for bad in ({"seat_mode": "sometimes"}, {"requires_governed_routing": "yes"}, {"seat_models": []},
                {"seat_models": ["claude sonnet"]}):
        with pytest.raises(AgentGatewayPolicyError):
            normalize_agent_gateway_policy(bad)


@pytest.mark.asyncio
async def test_gateway_routes_answer_each_token_failure_with_its_reason(client, db):
    workspace_id = await _workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="member")
    await db.commit()
    gateway = await _gateway_headers(db, user_id, workspace_id)
    platform = {**gateway, "authorization": (await _bearer(user_id))["Authorization"]}
    allowed = await client.get(POLICY, headers=gateway)
    missing = await client.get(POLICY, headers={k: v for k, v in gateway.items() if k != "authorization"})
    wrong_audience = await client.get(POLICY, headers=platform)
    garbage = await client.get(POLICY, headers={**gateway, "authorization": "Bearer not-a-token"})
    model = await client.post("/api/v1/model-gateway/anthropic/v1/messages", json=_body(),
                              headers={**gateway, "authorization": "Bearer not-a-token"})

    assert (allowed.status_code, allowed.json()["state"]) == (200, "allowed")
    assert (missing.status_code, missing.json()["reason"]) == (401, "gateway_token_missing")
    assert (wrong_audience.status_code, wrong_audience.json()["reason"]) == (401, "gateway_token_invalid")
    assert (garbage.status_code, garbage.json()["reason"]) == (401, "gateway_token_invalid")
    assert model.status_code == 401 and "gateway_token_invalid" in model.json()["error"]["message"]


@pytest.mark.asyncio
async def test_a_strict_workspace_still_gets_the_read_only_assistant(client, db):
    from app.models import Project

    workspace_id = await _workspace(db, classification="confidential")
    user_id = await seed_member(db, workspace_id=workspace_id, role="member")
    project = await db.get(Project, workspace_id)
    project.config = {**(project.config or {}), "agent_gateway_policy": {
        **((project.config or {}).get("agent_gateway_policy") or {}), "free_sessions": "read_only"}}
    await db.commit()
    answer = await _register(client, await _gateway_headers(db, user_id, workspace_id), profile="governed")
    assert answer.json()["platform_agent"]["capability_class"] == "read_only"


@pytest.mark.asyncio
async def test_a_removed_needs_auth_mark_is_kept_on_the_session_and_counted(client, db):
    # A device turn's launcher removes Claude Code's "needs authentication" mark for the platform server (a broken
    # turn's mark would hide the platform tools for ~15 minutes) and says so at registration.
    from app.models import Session
    from app.services.agent_gateway.contract import SESSION_KEY_METADATA
    from app.services.observability import device_report_metrics, workflow_metrics

    workflow_metrics.reset()
    workspace_id = await _workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="member")
    await db.commit()
    key = str(uuid.uuid4())

    answer = await client.post(REGISTER, json={"profile": "governed", "client": "octryx-claude-device",
                                               "client_version": "0.2.0", "mcp_auth_cache_cleared": True},
                               headers=await _gateway_headers(db, user_id, workspace_id, key))

    assert answer.status_code == 200
    sessions = (await db.execute(select(Session))).scalars().all()
    session = next(row for row in sessions if (row.metadata_ or {}).get(SESSION_KEY_METADATA) == key)
    assert session.metadata_["mcp_auth_cache_cleared"] is True
    assert device_report_metrics.DEVICE_MCP_AUTH_CLEARED.series[("governed",)] == 1

    await _register(client, await _gateway_headers(db, user_id, workspace_id), profile="governed")
    assert device_report_metrics.DEVICE_MCP_AUTH_CLEARED.series[("governed",)] == 1  # nothing removed: not counted
