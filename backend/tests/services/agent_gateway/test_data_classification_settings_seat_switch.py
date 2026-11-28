"""The seat switch: written through the governed path, the separate Codex key, governed routing, the classification reason and invalid stored policies."""

from __future__ import annotations

import pytest

from app.services.agent_gateway.seat_policy_keys import BASELINE_SEAT_MODELS
from tests.knowledge_evidence_seed_support import seed_member
from tests.support.data_classification_settings_support import (  # noqa: F401
    _actions,
    _admin_id,
    _bearer,
    _config,
    _route,
    _seat_route,
    _workspace,
    env,
)


@pytest.mark.asyncio
async def test_the_seat_switch_is_written_through_the_governed_path_and_keeps_the_baseline(client, db, env):  # noqa: F811
    workspace_id = await _workspace(db, {"data_policy": {"classification": "internal"}})
    member = await seed_member(db, workspace_id=workspace_id, role="member")
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    await db.commit()

    refused = await client.put(_seat_route(workspace_id), json={"seat_mode": "allowed"}, headers=await _bearer(member))
    invalid = await client.put(_seat_route(workspace_id), json={"seat_mode": "sometimes"}, headers=await _bearer(owner))
    # Allowing the seat loosens: a platform admin's (workspace_settings.bounds), not the owner's.
    owner_allows = await client.put(_seat_route(workspace_id), json={"seat_mode": "allowed"},
                                    headers=await _bearer(owner))
    allowed = await client.put(_seat_route(workspace_id), json={"seat_mode": "allowed"},
                               headers=await _bearer(await _admin_id(db)))
    policy = await client.get(_route(workspace_id), headers=await _bearer(member))

    assert refused.status_code == 403 and invalid.status_code == 422
    assert owner_allows.status_code == 403 and owner_allows.json()["detail"]["code"] == "platform_admin_required"
    assert allowed.json() == {"project_id": workspace_id, "seat_mode": "allowed", "in_effect": True, "reason": None,
                              "codex_seat_mode": "forbidden", "codex_in_effect": True,
                              "codex_reason": None, "requires_governed_routing": False,
                              "seat_models": [*BASELINE_SEAT_MODELS],
                              "seat_models_default": [*BASELINE_SEAT_MODELS],
                              "seat_models_limits": {"max_models": 20, "max_model_id_chars": 100},
                              "seat_allows_governed_models": False, "codex_seat_models": None,
                              "invalid_settings": [], "can_edit": True, "can_loosen": True,
                              "seat_mode_set": True, "codex_seat_mode_set": False}
    assert (await _config(db, workspace_id))["agent_gateway_policy"] == {"seat_mode": "allowed"}
    assert policy.json()["seat_mode"] == "allowed"
    from app.services.agent_gateway.policy import load_workspace_policy

    loaded = await load_workspace_policy(db, workspace_id)
    assert loaded.source == "baseline" and loaded.policy.daily_budget_usd is not None and loaded.policy.tool_rules
    assert "admin.agent_gateway.seat_mode_updated" in await _actions(db, workspace_id)

    await client.put(_route(workspace_id), json={"classification": "confidential"}, headers=await _bearer(owner))
    after = (await client.get(_seat_route(workspace_id), headers=await _bearer(member))).json()
    assert (after["seat_mode"], after["in_effect"], after["reason"]) == (
        "allowed", False, "seat_classification_too_sensitive")


@pytest.mark.asyncio
async def test_the_codex_seat_switch_is_its_own_key_and_keeps_the_other_policy_keys(client, db, env):  # noqa: F811
    workspace_id = await _workspace(db, {"data_policy": {"classification": "internal"},
                                         "agent_gateway_policy": {"seat_mode": "allowed", "seat_models": ["claude-sonnet-5"]}})
    member = await seed_member(db, workspace_id=workspace_id, role="member")
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    await db.commit()

    refused = await client.put(_seat_route(workspace_id), json={"codex_seat_mode": "allowed"}, headers=await _bearer(member))
    invalid = await client.put(_seat_route(workspace_id), json={"codex_seat_mode": "yes"}, headers=await _bearer(owner))
    owner_allows = await client.put(_seat_route(workspace_id), json={"codex_seat_mode": "allowed"},
                                    headers=await _bearer(owner))
    allowed = await client.put(_seat_route(workspace_id), json={"codex_seat_mode": "allowed"},
                               headers=await _bearer(await _admin_id(db)))
    stored = (await _config(db, workspace_id))["agent_gateway_policy"]
    back = await client.put(_seat_route(workspace_id), json={"codex_seat_mode": "forbidden"}, headers=await _bearer(owner))

    assert refused.status_code == 403 and owner_allows.status_code == 403
    assert invalid.status_code == 422 and invalid.json()["detail"] == {"errors": [{"code": "invalid_seat_mode"}]}
    assert (allowed.json()["codex_seat_mode"], allowed.json()["codex_in_effect"], allowed.json()["seat_mode"]) == (
        "allowed", True, "allowed")
    assert stored == {"seat_mode": "allowed", "seat_models": ["claude-sonnet-5"], "codex_seat_mode": "allowed"}
    assert (back.json()["codex_seat_mode"], back.json()["codex_reason"]) == ("forbidden", "codex_seat_mode_forbidden")
    assert (await _config(db, workspace_id))["agent_gateway_policy"]["seat_mode"] == "allowed"


@pytest.mark.asyncio
async def test_requires_governed_routing_blocks_the_codex_seat_too_and_says_so(client, db, env):  # noqa: F811
    workspace_id = await _workspace(db, {"data_policy": {"classification": "internal"},
                                         "agent_gateway_policy": {"seat_mode": "allowed", "codex_seat_mode": "allowed"}})
    member = await seed_member(db, workspace_id=workspace_id, role="member")
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    await db.commit()
    before = (await client.get(_seat_route(workspace_id), headers=await _bearer(member))).json()

    strict = await client.put(_seat_route(workspace_id), json={"requires_governed_routing": True},
                              headers=await _bearer(owner))

    assert (before["codex_in_effect"], before["codex_reason"]) == (True, None)
    answer = strict.json()
    assert strict.status_code == 200 and answer["requires_governed_routing"] is True
    assert (answer["codex_seat_mode"], answer["codex_in_effect"], answer["codex_reason"]) == (
        "allowed", False, "seat_requires_governed_routing")
    assert (answer["seat_mode"], answer["in_effect"], answer["reason"]) == (
        "allowed", False, "seat_requires_governed_routing")


@pytest.mark.asyncio
async def test_the_classification_reason_wins_over_the_switch_off(client, db, env):  # noqa: F811
    workspace_id = await _workspace(db, {"data_policy": {"classification": "confidential"},
                                         "agent_gateway_policy": {"requires_governed_routing": True}})
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    await db.commit()

    seat = (await client.get(_seat_route(workspace_id), headers=await _bearer(owner))).json()
    card = (await client.get(_route(workspace_id), headers=await _bearer(owner))).json()

    assert (seat["seat_mode"], seat["in_effect"], seat["reason"]) == ("forbidden", False,
                                                                      "seat_classification_too_sensitive")
    assert card["effects"]["reasons"]["seat_mode_allowed"] == "seat_classification_too_sensitive"
    internal = next(level for level in card["levels"] if level["value"] == "internal")
    assert internal["effects"]["reasons"]["seat_mode_allowed"] == "seat_requires_governed_routing"


@pytest.mark.asyncio
@pytest.mark.parametrize("stored", [{"tool_rules": "not-a-list"}, {"unknown_key": 1}, "allowed"])
async def test_the_seat_switch_on_an_invalid_stored_policy_is_a_coded_422(client, db, env, stored):  # noqa: F811
    workspace_id = await _workspace(db, {"data_policy": {"classification": "internal"},
                                         "agent_gateway_policy": stored})
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    await db.commit()

    refused = await client.put(_seat_route(workspace_id), json={"seat_mode": "allowed"}, headers=await _bearer(owner))

    assert refused.status_code == 422
    assert refused.json()["detail"] == {"errors": [{"code": "agent_gateway_policy_invalid"}]}
    assert (await _config(db, workspace_id))["agent_gateway_policy"] == stored
    assert "admin.agent_gateway.seat_mode_updated" not in await _actions(db, workspace_id)
