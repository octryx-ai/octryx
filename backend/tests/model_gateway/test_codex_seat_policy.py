"""Codex seat registration, client policy, seat models and device runs follow the workspace's Codex seat policy."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AgentPresence
from app.services.agent_gateway.policy_keys import AgentGatewayPolicyError
from app.services.agent_gateway.policy_normalize import normalize_agent_gateway_policy
from tests.agent_gateway.seat_presence_support import REGISTER
from tests.model_gateway.codex_seat_support import (  # noqa: F401
    CODEX_POLICY,
    MODEL,
    ROUTE,
    _body,
    _codex_session,
    _headers,
    _member,
    _register,
    chatgpt,
)

# --- policy ------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("classification", "policy", "reason"), [
    ("confidential", None, "seat_classification_too_sensitive"),  # unset: open up to internal
    ("internal", {"seat_mode": "allowed", "codex_seat_mode": "forbidden"}, "codex_seat_mode_forbidden"),
    ("internal", {"codex_seat_mode": "allowed", "requires_governed_routing": True}, "seat_requires_governed_routing"),
    ("confidential", CODEX_POLICY, "seat_classification_too_sensitive"),
    ("secret", CODEX_POLICY, "seat_classification_too_sensitive"),
    (None, CODEX_POLICY, "seat_classification_unresolved"),
    ("internal", {**CODEX_POLICY, "engines": {"allowed": ["claude_code"]}}, "engine_not_allowed_in_workspace"),
])
async def test_a_codex_seat_registration_checks_the_codex_seat_policy(client, db, classification, policy, reason):
    workspace_id, _user, gateway = await _member(db, classification=classification, policy=policy)

    refused = await _register(client, gateway)

    assert (refused.status_code, refused.json()["reason"]) == (403, reason)
    assert (await db.execute(select(AgentPresence).where(AgentPresence.project_id == workspace_id))).first() is None


@pytest.mark.asyncio
async def test_claude_seat_registration_is_unchanged(client, db):
    _ws, _user, codex_only = await _member(db, policy={**CODEX_POLICY, "seat_mode": "forbidden"})
    refused = await _register(client, codex_only, engine=None)
    assert (refused.status_code, refused.json()["reason"]) == (403, "seat_mode_forbidden")

    _ws, _user, claude = await _member(db, policy={"seat_mode": "allowed"})
    registered = await _register(client, claude, engine="claude_code")
    assert registered.status_code == 200 and registered.json()["seat_credential"]


def test_codex_seat_mode_is_a_validated_policy_key():
    assert normalize_agent_gateway_policy({"codex_seat_mode": "allowed"})["codex_seat_mode"] == "allowed"
    with pytest.raises(AgentGatewayPolicyError):
        normalize_agent_gateway_policy({"codex_seat_mode": "yes"})


@pytest.mark.asyncio
@pytest.mark.parametrize(("policy", "expected"), [
    (None, ("allowed", True, None)),  # unset at internal: open
    ({"codex_seat_mode": "forbidden"}, ("forbidden", False, "codex_seat_mode_forbidden")),
    (CODEX_POLICY, ("allowed", True, None)),
    ({**CODEX_POLICY, "engines": {"allowed": ["claude_code"]}}, ("allowed", False, "engine_not_allowed_in_workspace")),
])
async def test_the_client_policy_reports_the_codex_seat_like_registration_decides_it(client, db, policy, expected):
    _workspace_id, _user, gateway = await _member(db, policy=policy)

    answer = await client.get(REGISTER.replace("/sessions/register", "/client-policy"), headers=gateway)

    seat = answer.json()["codex_seat"]
    assert (seat["codex_seat_mode"], seat["allowed"], seat["reason"]) == expected
    assert answer.json()["local_models"] == {"permissive_only": True}


@pytest.mark.asyncio
async def test_a_codex_model_may_be_a_seat_target_when_the_workspace_allows_the_codex_seat(db):
    """A Codex run's reviewer on a Codex model is not refused device_model_not_allowed by a Claude-only seat list."""
    from app.services.devices.device_models import check_device_model

    allowed_ws, allowed_user, _ = await _member(db, policy=CODEX_POLICY)
    closed_ws, closed_user, _ = await _member(db, policy={"seat_mode": "allowed", "codex_seat_mode": "forbidden"})

    assert await check_device_model(db, user_id=allowed_user, workspace_id=allowed_ws, profile="seat",
                                    device_id="", model="gpt-6-luna") is None
    assert await check_device_model(db, user_id=closed_user, workspace_id=closed_ws, profile="seat",
                                    device_id="", model="gpt-6-luna") == ("denied", "device_model_not_allowed")
    assert await check_device_model(db, user_id=allowed_user, workspace_id=allowed_ws, profile="seat",
                                    device_id="", model="gpt-unknown-x") == ("denied", "device_model_not_allowed")


@pytest.mark.asyncio
async def test_codex_seat_models_narrow_the_codex_seat(client, db, chatgpt):  # noqa: F811
    """A Workspace may name the Codex models its Codex seat allows; another model is refused (403), never
    swapped; device turns and run targets follow the same list."""
    from app.services.devices.device_models import check_device_model

    policy = {**CODEX_POLICY, "codex_seat_models": ["gpt-6.1-sol", MODEL]}
    workspace_id, user_id, gateway, credential = await _codex_session(client, db, policy=policy)
    allowed = await client.post(ROUTE, json=_body(), headers=_headers(gateway, credential))
    assert allowed.status_code == 200, allowed.text
    refused = await client.post(ROUTE, json={**_body(), "model": "gpt-6-astra"}, headers=_headers(gateway, credential))
    assert refused.status_code == 403 and "seat_model_not_allowed" in refused.text
    assert len(chatgpt.requests) == 1

    assert await check_device_model(db, user_id=user_id, workspace_id=workspace_id, profile="seat", device_id="",
                                    model="gpt-6.1-sol") is None
    assert await check_device_model(db, user_id=user_id, workspace_id=workspace_id, profile="seat", device_id="",
                                    model="gpt-6-luna") == ("denied", "device_model_not_allowed")


def test_codex_seat_models_are_validated_like_seat_models():
    from app.services.agent_gateway.seat_policy_keys import SeatPolicyError, normalize_seat_policy

    assert normalize_seat_policy({"codex_seat_models": ["gpt-6-luna", "gpt-6-luna"]}, "p") == {
        "codex_seat_models": ["gpt-6-luna"]}
    for bad in ([], "gpt-6-luna", ["bad model"]):
        with pytest.raises(SeatPolicyError):
            normalize_seat_policy({"codex_seat_models": bad}, "p")


@pytest.mark.asyncio
async def test_a_codex_workspaces_seat_device_run_is_decided_by_the_codex_seat_switch(db, monkeypatch):
    """A Codex start is not refused seat_mode_forbidden when the Workspace allows the Codex seat; the Claude seat's
    switch does not decide."""
    import uuid

    from app.models import UserDevice
    from app.services.devices import device_policy

    async def platform_on(_db):
        return True

    monkeypatch.setattr(device_policy, "device_runs_platform_enabled", platform_on)
    runs = {"enabled": True, "allowed_profiles": ["seat", "governed"]}
    codex_ws, codex_user, _ = await _member(db, policy={
        **CODEX_POLICY, "seat_mode": "forbidden", "device_runs": runs,
        "engines": {"allowed": ["claude_code", "codex"], "default": "codex"}})
    claude_ws, claude_user, _ = await _member(db, policy={
        **CODEX_POLICY, "seat_mode": "forbidden", "device_runs": runs,
        "engines": {"allowed": ["claude_code", "codex"], "default": "claude_code"}})

    async def decide(user_id: str, workspace_id: str):
        device = UserDevice(owner_user_id=user_id, name="Mac", name_key=f"mac-{uuid.uuid4().hex[:6]}", os="macos",
                            public_key="k", profiles=["seat"], folders=["/w"])
        db.add(device)
        await db.flush()
        return await device_policy.device_run_decision(db, user_id=user_id, device=device, workspace_id=workspace_id,
                                                       profile="seat", folder_allowlisted=True)

    assert (await decide(codex_user, codex_ws)).allowed
    refused = await decide(claude_user, claude_ws)
    assert not refused.allowed and refused.reason == "seat_mode_forbidden"
