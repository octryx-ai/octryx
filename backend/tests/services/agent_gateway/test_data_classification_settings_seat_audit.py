"""Seat settings are saved alone and audited, refused settings write nothing, owners may only tighten and model lists stay valid."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.services.agent_gateway.seat_policy_keys import BASELINE_SEAT_MODELS
from tests.knowledge_evidence_seed_support import seed_member
from tests.support.data_classification_settings_support import (  # noqa: F401
    _admin_id,
    _bearer,
    _config,
    _seat_route,
    _workspace,
    env,
)


async def _seat_audits(db, resource_id: str) -> list[dict]:
    rows = await db.execute(select(AuditLog).where(AuditLog.resource_id == resource_id,
                                                   AuditLog.action == "admin.agent_gateway.seat_mode_updated"))
    return [dict(row.details) for row in rows.scalars()]


@pytest.mark.asyncio
async def test_each_seat_setting_is_saved_alone_with_before_and_after_in_the_audit(client, db, env):  # noqa: F811
    stored_policy = {"seat_mode": "allowed", "session_budget": {"per_user_daily_usd": 7.0}}
    workspace_id = await _workspace(db, {"data_policy": {"classification": "internal"},
                                         "agent_gateway_policy": stored_policy})
    member = await seed_member(db, workspace_id=workspace_id, role="member")
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    await db.commit()

    admin = await _admin_id(db)

    async def save(body, user=admin):
        return await client.put(_seat_route(workspace_id), json=body, headers=await _bearer(user))

    first = (await client.get(_seat_route(workspace_id), headers=await _bearer(member))).json()
    assert (first["requires_governed_routing"], first["seat_models"], first["seat_allows_governed_models"]) == (
        False, [*BASELINE_SEAT_MODELS], False), "absent keys answer their defaults"

    assert (await save({"seat_models": ["claude-sonnet-5"]}, member)).status_code == 403
    models = await save({"seat_models": ["claude-sonnet-5", "claude-haiku-5", "claude-sonnet-5"]})
    governed = await save({"seat_allows_governed_models": True})
    strict = await save({"requires_governed_routing": True}, owner)  # tightening: the owner may

    assert models.status_code == 200 and models.json()["seat_models"] == ["claude-sonnet-5", "claude-haiku-5"]
    assert governed.json()["seat_allows_governed_models"] is True
    assert (strict.json()["requires_governed_routing"], strict.json()["in_effect"], strict.json()["reason"]) == (
        True, False, "seat_requires_governed_routing")
    assert (await _config(db, workspace_id))["agent_gateway_policy"] == {
        **stored_policy, "seat_models": ["claude-sonnet-5", "claude-haiku-5"], "seat_allows_governed_models": True,
        "requires_governed_routing": True}
    audits = await _seat_audits(db, workspace_id)
    assert [(audit["before"], audit["after"]) for audit in audits] == [
        ({"seat_models": [*BASELINE_SEAT_MODELS]}, {"seat_models": ["claude-sonnet-5", "claude-haiku-5"]}),
        ({"seat_allows_governed_models": False}, {"seat_allows_governed_models": True}),
        ({"requires_governed_routing": False}, {"requires_governed_routing": True}),
    ]

    codex = await save({"codex_seat_mode": "allowed"})
    assert codex.status_code == 200
    assert (await _seat_audits(db, workspace_id))[-1] == {
        "codex_seat_mode": "allowed", "before": {"codex_seat_mode": "forbidden"}, "after": {"codex_seat_mode": "allowed"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("body, code", [
    ({"seat_models": []}, "invalid_list"),
    ({"seat_models": [f"m{index}" for index in range(21)]}, "invalid_list"),
    ({"seat_models": ["x" * 101]}, "invalid_model_id"),
    ({"seat_models": ["claude sonnet"]}, "invalid_model_id"),
    ({"seat_models": "claude-sonnet-5"}, "invalid_list"),
    ({"requires_governed_routing": "yes"}, "invalid_flag"),
    ({"seat_allows_governed_models": 1}, "invalid_flag"),
    ({"seat_mode": ["allowed"]}, "invalid_seat_mode"),
    ({"seat_models": ["claude-sonnet-5"], "seat_allows_governed_models": True}, "one_setting_per_call"),
    ({"seat_mode": "allowed", "seat_budget": 5}, "unknown_setting"),
])
async def test_a_refused_seat_setting_is_coded_and_writes_nothing(client, db, env, body, code):  # noqa: F811
    stored_policy = {"seat_mode": "allowed", "seat_models": ["claude-opus-5-5"]}
    workspace_id = await _workspace(db, {"data_policy": {"classification": "internal"},
                                         "agent_gateway_policy": stored_policy})
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    await db.commit()

    refused = await client.put(_seat_route(workspace_id), json=body, headers=await _bearer(owner))

    assert refused.status_code == 422 and refused.json()["detail"] == {"errors": [{"code": code}]}
    assert (await _config(db, workspace_id))["agent_gateway_policy"] == stored_policy
    assert await _seat_audits(db, workspace_id) == []


@pytest.mark.asyncio
async def test_the_longest_allowed_model_list_is_accepted(client, db, env):  # noqa: F811
    workspace_id = await _workspace(db, {"data_policy": {"classification": "internal"}})
    await db.commit()
    models = [f"model-{index:02d}-" + "x" * 91 for index in range(20)]
    assert all(len(model) == 100 for model in models)

    saved = await client.put(_seat_route(workspace_id), json={"seat_models": models},
                             headers=await _bearer(await _admin_id(db)))

    assert saved.status_code == 200 and saved.json()["seat_models"] == models


@pytest.mark.asyncio
@pytest.mark.parametrize("stored, body, path", [
    ({"seat_mode": "forbidden"}, {"seat_mode": "allowed"}, "seat_mode"),
    ({"codex_seat_mode": "forbidden"}, {"codex_seat_mode": "allowed"}, "codex_seat_mode"),
    ({"requires_governed_routing": True}, {"requires_governed_routing": False}, "requires_governed_routing"),
    ({"seat_allows_governed_models": False}, {"seat_allows_governed_models": True}, "seat_allows_governed_models"),
    ({"seat_models": ["claude-sonnet-5"]}, {"seat_models": ["claude-sonnet-5", "claude-opus-5-5"]}, "seat_models"),
    ({"codex_seat_models": ["gpt-5.5"]}, {"codex_seat_models": ["gpt-5.5", "gpt-5.5-mini"]}, "codex_seat_models"),
    ({"codex_seat_models": ["gpt-5.5"]}, {"codex_seat_models": None}, "codex_seat_models"),
])
async def test_a_workspace_owner_may_only_tighten_the_seat_settings(client, db, env, stored, body, path):  # noqa: F811
    workspace_id = await _workspace(db, {"data_policy": {"classification": "internal"}, "agent_gateway_policy": stored})
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    await db.commit()

    refused = await client.put(_seat_route(workspace_id), json=body, headers=await _bearer(owner))
    view = (await client.get(_seat_route(workspace_id), headers=await _bearer(owner))).json()

    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "platform_admin_required"
    assert refused.json()["detail"]["path"] == path
    assert (await _config(db, workspace_id))["agent_gateway_policy"] == stored
    assert await _seat_audits(db, workspace_id) == []
    assert (view["can_edit"], view["can_loosen"]) == (True, False)


@pytest.mark.asyncio
async def test_an_invalid_stored_seat_value_is_shown_as_invalid_not_as_the_default(client, db, env):  # noqa: F811
    workspace_id = await _workspace(db, {"data_policy": {"classification": "internal"},
                                         "agent_gateway_policy": {"seat_mode": "allowed", "seat_models": "opus"}})
    member = await seed_member(db, workspace_id=workspace_id, role="member")
    await db.commit()

    view = (await client.get(_seat_route(workspace_id), headers=await _bearer(member))).json()

    assert view["invalid_settings"] == ["seat_models"] and view["seat_models"] is None
    assert view["seat_mode"] == "allowed"


@pytest.mark.asyncio
async def test_the_codex_seat_model_list_is_set_tightened_and_cleared_through_the_seat_route(client, db, env):  # noqa: F811
    stored = {"seat_mode": "allowed", "seat_models": ["claude-sonnet-5"]}
    workspace_id = await _workspace(db, {"data_policy": {"classification": "internal"}, "agent_gateway_policy": stored})
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    await db.commit()
    put = lambda body, user: client.put(_seat_route(workspace_id), json=body, headers=user)  # noqa: E731

    start = (await client.get(_seat_route(workspace_id), headers=await _bearer(owner))).json()
    restricted = await put({"codex_seat_models": ["gpt-5.5", "gpt-5.5-mini"]}, await _bearer(owner))
    removed = await put({"codex_seat_models": ["gpt-5.5"]}, await _bearer(owner))
    invalid = await put({"codex_seat_models": []}, await _bearer(owner))
    cleared = await put({"codex_seat_models": None}, await _bearer(await _admin_id(db)))

    assert start["codex_seat_models"] is None
    assert restricted.status_code == 200 and restricted.json()["codex_seat_models"] == ["gpt-5.5", "gpt-5.5-mini"]
    assert removed.json()["codex_seat_models"] == ["gpt-5.5"]
    assert invalid.status_code == 422
    assert cleared.status_code == 200 and cleared.json()["codex_seat_models"] is None
    assert (await _config(db, workspace_id))["agent_gateway_policy"] == stored
