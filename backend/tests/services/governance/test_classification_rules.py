"""Added rules from the closed effect catalog and stricter-only Workspace overrides."""

from __future__ import annotations

import uuid

import pytest

from app.models import Project
from app.services.data_classification.effect_rules import (
    EffectRule,
    knowledge_sharing_off,
    set_effect_rules,
    web_search_off,
)
from app.services.data_classification.levels import reset_level_registry
from app.services.data_classification.policy_matrix import load_classification_policy
from app.services.data_classification.workspace_overrides import apply_overrides, workspace_level_rules
from app.services.governance.approval_rule import APPROVAL_RULE_CONFIG_KEY
from app.services.mcp_access_policy import mcp_server_access_decision
from app.services.policy_engine.baseline import load_baseline
from app.services.system_config.values import set_system_config_value
from tests.policy_engine_support import bearer, make_user

ROUTE = "/api/v1/admin/data-classification/policy"


@pytest.fixture(autouse=True)
def _clean_state():
    reset_level_registry()
    set_effect_rules(())
    yield
    reset_level_registry()
    set_effect_rules(())


async def _workspace(db, level: str = "confidential", **config) -> Project:
    project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:6]}", is_active=True,
                      config={"data_policy": {"classification": level}, **config})
    db.add(project)
    await db.commit()
    return project


@pytest.mark.asyncio
async def test_an_added_rule_is_published_and_enforced_from_its_level_up(client, db):
    admin = await make_user(db, admin=True)
    await set_system_config_value(db, key=APPROVAL_RULE_CONFIG_KEY, value="single_admin")
    await db.commit()
    rules = [{"effect": "web_search", "param": "off", "from_level": "confidential"},
             {"effect": "mcp_server", "param": "ticket-desk", "from_level": "restricted"}]
    saved = await client.put(f"{ROUTE}/draft", json={"levels": [], "effect_rules": rules}, headers=bearer(admin))
    assert saved.status_code == 200, saved.text
    draft = saved.json()["draft"]
    assert [line["text"] for line in draft["changes"]] == [
        "Rule added: Web search off at Confidential and above",
        "Rule added: MCP server access ticket-desk off at Restricted and above"]
    generated = (await client.get(f"{ROUTE}/generated?source=draft", headers=bearer(admin))).json()["policies"]
    web = next(item for item in generated if item["id"] == "classification:confidential+:web_search")
    assert 'resource == Tool::"web_search"' in web["text"] and "classification_rank >= 300" in web["text"]
    assert not web_search_off("confidential"), "nothing live before publishing"

    version = (await client.post(f"{ROUTE}/draft/submit", json={}, headers=bearer(admin))).json()["draft"]["version"]
    assert (await client.post(f"{ROUTE}/versions/{version}/approve", headers=bearer(admin))).status_code == 200
    assert web_search_off("confidential") and web_search_off("secret") and not web_search_off("internal")

    config = {"data_policy": {"classification": "restricted"}, "mcp_policy": {"enabled_servers": ["ticket-desk"]}}
    refused = mcp_server_access_decision("ticket-desk", config)
    assert refused.allowed is False and refused.reason == "classification_mcp_server_off"
    lower = {**config, "data_policy": {"classification": "confidential"}}
    assert mcp_server_access_decision("ticket-desk", lower).allowed
    assert mcp_server_access_decision("docs", config).reason == "mcp_server_not_active_for_project", "other servers"


@pytest.mark.asyncio
async def test_only_effects_with_an_enforcement_point_can_be_added(client, db):
    admin = await make_user(db, admin=True)
    for rule, code in [
        ({"effect": "export", "param": "off", "from_level": "internal"}, "classification_effect_unknown"),
        ({"effect": "web_search", "param": "read", "from_level": "internal"}, "classification_effect_param_invalid"),
        ({"effect": "web_search", "param": "off", "from_level": "top"}, "classification_effect_level_unknown"),
        ({"effect": "mcp_server", "param": "bad name!", "from_level": "internal"}, "classification_effect_param_invalid"),
    ]:
        refused = await client.put(f"{ROUTE}/draft", json={"levels": [], "effect_rules": [rule]}, headers=bearer(admin))
        assert refused.status_code == 422 and refused.json()["detail"]["code"] == code, refused.text
    listing = (await client.get(f"{ROUTE}/versions", headers=bearer(admin))).json()
    catalog = {item["key"]: item["enforced"] for item in listing["effect_catalog"]}
    assert catalog == {"web_search": True, "mcp_server": True, "knowledge_sharing": True, "export": False,
                       "share_chat": False}


def test_knowledge_sharing_off_applies_from_its_level():
    set_effect_rules((EffectRule("knowledge_sharing", "off", "restricted"),))
    assert knowledge_sharing_off("restricted") and knowledge_sharing_off("secret")
    assert not knowledge_sharing_off("confidential") and not knowledge_sharing_off(None)


@pytest.mark.asyncio
async def test_a_workspace_override_can_only_be_stricter_and_survives_a_level_change(client, db):
    admin = await make_user(db, admin=True)
    project = await _workspace(db, "internal")
    route = f"{ROUTE}/workspaces/{project.id}/overrides"

    looser = await client.put(route, json={"overrides": {"log_masking_required": False, "seat_allowed": True,
                                                         "connectors": {"jira": "read_write"}}}, headers=bearer(admin))
    assert looser.status_code == 200 and looser.json()["overrides"] == {}, "equal to the level: nothing to store"
    stricter = {"seat_allowed": False, "connectors": {"jira": "read"}, "transcript_retention_days": 30}
    saved = await client.put(route, json={"overrides": stricter}, headers=bearer(admin))
    assert saved.status_code == 200 and saved.json()["overrides"] == stricter

    await db.refresh(project)
    rules = await workspace_level_rules(db, project.config, "internal")
    assert rules.seat_allowed is False and rules.connector_access("jira") == "read"
    assert rules.transcript_retention_days == 30
    baseline = (await load_baseline(db)).text
    assert f'@id("workspace:{project.id}:classification:seat-allowed")' in baseline
    assert f'@id("workspace:{project.id}:classification:connector:jira:read-only")' in baseline

    moved = await client.put(f"/api/v1/workspaces/{project.id}/data-classification", json={"classification": "public"},
                             headers=bearer(admin))
    assert moved.status_code == 200, moved.text
    await db.refresh(project)
    assert project.config["data_policy"]["overrides"] == stricter, "a level change keeps the overrides"

    cleared = await client.put(route, json={"overrides": {}}, headers=bearer(admin))
    assert cleared.status_code == 200
    await db.refresh(project)
    assert project.config["data_policy"].get("overrides", {}) == {}, "removing every override clears them"

    restricted = (await load_classification_policy(db)).rules_for("restricted")
    assert apply_overrides(restricted, {"seat_allowed": True}).seat_allowed is restricted.seat_allowed, "never widens"


@pytest.mark.asyncio
async def test_a_looser_override_is_refused_with_the_reason(client, db):
    admin = await make_user(db, admin=True)
    project = await _workspace(db, "confidential")
    refused = await client.put(f"{ROUTE}/workspaces/{project.id}/overrides",
                               json={"overrides": {"seat_allowed": True}}, headers=bearer(admin))
    assert refused.status_code == 422
    assert refused.json()["detail"] == {"code": "classification_override_looser", "path": "overrides.seat_allowed",
                                        "reason": "the level already sets seat_allowed to False"}
    unknown = await client.put(f"{ROUTE}/workspaces/{project.id}/overrides",
                               json={"overrides": {"allowed_model_aliases": []}}, headers=bearer(admin))
    assert unknown.status_code == 422 and unknown.json()["detail"]["code"] == "classification_override_unknown"
