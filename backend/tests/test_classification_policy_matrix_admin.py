"""The classification policy matrix admin API: reads, validation, stored differences, audit and reset, fail-closed reads, computed effects and the member policy summary."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog, SystemConfig
from app.services.agent_gateway.policy_keys import BASELINE_POLICY
from app.services.data_classification.policy_matrix import load_classification_policy
from app.services.data_classification.policy_matrix_admin import set_classification_policy
from app.services.data_classification.policy_rules import POLICY_MATRIX_CONFIG_KEY
from tests.classification_policy_matrix_support import (
    REMOTE_SPACE,
    RERANKER,
    ROUTE,
    _admin_id,
    _bearer,
    _catalog_clearance,
    _gateway,
    _matrix,
    _summary,
    _workspace,
)
from tests.knowledge_evidence_seed_support import seed_member
from tests.model_gateway.conftest import ALIAS, VIRTUAL_KEY, gateway_provider

# --- admin API, validation, audit ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anyone_reads_the_default_matrix_and_only_platform_admins_write_it(client, db):
    member = await seed_member(db, workspace_id=await _workspace(db), role="owner")
    await db.commit()

    read = await client.get(ROUTE, headers=await _bearer(member))
    write = await client.put(f"{ROUTE}/draft", json={"levels": []}, headers=await _bearer(member))
    admin_read = await client.get(ROUTE, headers=await _bearer(await _admin_id(db)))

    body = read.json()
    assert read.status_code == 200 and body["state"] == "default" and body["can_edit"] is False
    assert [item["level"] for item in body["levels"]] == ["public", "internal", "confidential", "restricted", "secret"]
    assert [item["rules"]["seat_allowed"] for item in body["levels"]] == [True, True, False, False, False]
    # Every stored rule is its default; the per-level model lists are derived from the Model catalog (no model).
    derived = {"allowed_model_aliases"}
    assert body["derived_rules"] == sorted(derived)
    assert all({key: value for key, value in item["rules"].items() if key not in derived}
               == {key: value for key, value in body["defaults"][item["level"]].items() if key not in derived}
               for item in body["levels"])
    # No gateway connection: no level narrows the models (``None``), there is no catalog to derive from.
    assert all(item["rules"]["allowed_model_aliases"] is None for item in body["levels"])
    assert body["levels"][0]["rules"]["connectors"]["kubernetes"] == "read_write"
    assert body["updated_at"] is None and body["updated_by"] is None
    assert write.status_code == 403 and admin_read.json()["can_edit"] is True
    assert (await client.get(ROUTE)).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "code", "path"),
    [
        ({"levels": {}}, "classification_policy_levels_invalid", "levels"),
        ({"levels": [{"level": "top", "rules": {}}]}, "classification_policy_level_unknown", "levels[0].level"),
        ({"levels": [{"level": "public"}, {"level": "public"}]}, "classification_policy_level_duplicate",
         "levels[1].level"),
        ({"levels": [{"level": "public", "rules": {"x": 1}}]}, "classification_policy_rule_unknown",
         "levels[0].rules.x"),
        ({"levels": [{"level": "public", "rules": {"seat_allowed": "yes"}}]}, "classification_policy_rule_invalid",
         "levels[0].rules.seat_allowed"),
        ({"levels": [{"level": "public", "rules": {"transcript_retention_days": 0}}]},
         "classification_policy_rule_invalid", "levels[0].rules.transcript_retention_days"),
        ({"levels": [{"level": "public", "rules": {"connectors": {"gitlab": "none"}}}]},
         "classification_policy_connector_family_unknown", "levels[0].rules.connectors.gitlab"),
        ({"levels": [{"level": "public", "rules": {"connectors": {"jira": "write"}}}]},
         "classification_policy_connector_access_invalid", "levels[0].rules.connectors.jira"),
    ],
)
async def test_an_invalid_matrix_is_refused_with_a_code_and_nothing_is_stored(client, db, body, code, path):
    # Every change is a governed draft; the draft is validated like the live matrix.
    response = await client.put(f"{ROUTE}/draft", json=body, headers=await _bearer(await _admin_id(db)))

    assert response.status_code == 422
    assert response.json()["detail"] == {"code": code, "path": path}
    assert await db.get(SystemConfig, POLICY_MATRIX_CONFIG_KEY) is None


@pytest.mark.asyncio
async def test_a_write_stores_only_the_differences_audits_them_and_reset_removes_the_row(client, db):
    # The publish step of a governed version writes through this service function.
    admin = await _admin_id(db)
    change = [{"level": "internal", "rules": {
        "seat_allowed": False, "connectors": {"kubernetes": "none", "jira": "read_write"},
        "allowed_model_aliases": ["b", "a", "a"], "transcript_retention_days": 30}}]

    await set_classification_policy(db, levels=change, actor_id=admin)
    await db.commit()
    body = (await client.get(ROUTE, headers=await _bearer(admin))).json()
    await set_classification_policy(db, levels=[], actor_id=admin)
    await db.commit()
    reset = (await client.get(ROUTE, headers=await _bearer(admin))).json()

    internal = next(item["rules"] for item in body["levels"] if item["level"] == "internal")
    assert body["state"] == "configured" and body["updated_by"] == admin
    assert internal["seat_allowed"] is False and internal["connectors"]["kubernetes"] == "none"
    # The submitted model list is ignored: the list is derived from the Model catalog clearance (read-only).
    assert internal["allowed_model_aliases"] is None and internal["transcript_retention_days"] == 30
    assert "allowed_model_aliases" not in str((await db.get(SystemConfig, POLICY_MATRIX_CONFIG_KEY) or SystemConfig()).value)
    assert reset["state"] == "default" and await db.get(SystemConfig, POLICY_MATRIX_CONFIG_KEY) is None
    rows = (await db.execute(select(AuditLog).where(AuditLog.action == "admin.data_classification.policy_updated")
                             .order_by(AuditLog.created_at))).scalars().all()
    assert len(rows) == 2 and rows[0].user_id == admin
    changed = {(item["level"], item["rule"]) for item in rows[0].details["changes"]}
    assert changed == {("internal", "seat_allowed"), ("internal", "connectors"),
                       ("internal", "transcript_retention_days")}
    assert {(item["level"], item["rule"]) for item in rows[1].details["changes"]} == changed


@pytest.mark.asyncio
async def test_an_unreadable_stored_matrix_fails_closed(db):
    db.add(SystemConfig(key=POLICY_MATRIX_CONFIG_KEY, value='{"overrides": {"internal": {"seat_allowed": "x"}}}'))
    await db.commit()

    policy = await load_classification_policy(db)
    rules = policy.rules_for("public")

    assert policy.state == "invalid"
    assert (rules.seat_allowed, rules.reranker_allowed, rules.allowed_model_aliases) == (False, False, ())
    assert set(rules.connectors.values()) == {"none"}


# --- effects and the Workspace policy view -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_effects_are_computed_from_the_matrix(client, db, monkeypatch):
    monkeypatch.setenv("OCTRYX_KNOWLEDGE_RERANKER", RERANKER)
    monkeypatch.setenv("OCTRYX_KNOWLEDGE_EMBEDDING_SPACE", REMOTE_SPACE)
    monkeypatch.setenv("AWS_REGION", "eu-central-1")
    db.add(gateway_provider(name=f"litellm-{uuid.uuid4().hex[:6]}"))
    workspace_id = await _workspace(db, agent_gateway_policy={"seat_mode": "allowed"})
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    await db.commit()
    await set_classification_policy(db, actor_id=await _admin_id(db), levels=[{"level": "internal", "rules": {
        "seat_allowed": False, "reranker_allowed": False,
        "connectors": {"aws": "read"}, "log_masking_required": True}}])
    await db.commit()
    await _catalog_clearance(db, "public")

    body = (await client.get(f"/api/v1/workspaces/{workspace_id}/data-classification",
                             headers=await _bearer(owner))).json()

    effects = body["effects"]
    assert effects["seat_mode_allowed"] is False and effects["reranker_allowed"] is False
    assert effects["reasons"]["reranker_allowed"] == "classification_policy_reranker_forbidden"
    assert effects["remote_embeddings_allowed"] is True and effects["governed_models"] == []
    assert effects["connectors"]["aws"] == "read" and effects["log_masking_required"] is True
    public = next(level for level in body["levels"] if level["value"] == "public")
    assert public["effects"]["governed_models"] == [ALIAS] and public["rules"]["seat_allowed"] is True


@pytest.mark.asyncio
async def test_the_policy_summary_is_for_members_only_and_shows_the_effective_policy(client, db):
    await _gateway(db)
    workspace_id = await _workspace(
        db, agent_gateway_policy={**BASELINE_POLICY, "seat_mode": "allowed"},
        runtime_cost_limits={"agent_session_cost_limit_usd": 100, "agent_request_cost_limit_usd": 10},
    )
    member = await seed_member(db, workspace_id=workspace_id, role="member")
    outsider = await seed_member(db, workspace_id=await _workspace(db), role="owner")
    await db.commit()
    await _matrix(db, connectors={"kubernetes": "none"})

    response = await client.get(_summary(workspace_id), headers=await _bearer(member))
    hidden = await client.get(_summary(workspace_id), headers=await _bearer(outsider))
    missing = await client.get(_summary(str(uuid.uuid4())), headers=await _bearer(member))

    body = response.json()
    assert response.status_code == 200 and hidden.status_code == missing.status_code == 404
    assert body["classification"]["effective"] == "internal" and body["can_edit"] is False
    assert body["rules"]["connectors"]["kubernetes"] == "none" == body["connectors"]["kubernetes"]
    assert body["seat"] == {"seat_mode": "allowed", "in_effect": True, "reason": None, "seat_mode_set": True,
                            "codex_seat_mode_set": False}
    assert body["models"]["allowed_aliases"] == [ALIAS]
    assert body["budgets"] == {
        "per_user_daily_usd": {"value_usd": 200.0, "source": "workspace"},
        "session_cost_limit_usd": {"value_usd": 100.0, "source": "workspace"},
        "request_cost_limit_usd": {"value_usd": 10.0, "source": "workspace"},
    }
    gateway = body["agent_gateway_policy"]
    assert gateway["state"] == "ok" and gateway["source"] == "workspace" and len(gateway["tool_rules"]) == 8
    rules = {rule["id"]: rule for rule in gateway["tool_rules"]}
    assert rules["no-env-files"] == {"id": "no-env-files", "kind": "path_denied",
                                     "target": {"tools": ["Edit", "MultiEdit", "Read", "Write"], "glob": "**/.env"}}
    assert rules["kubectl-requires-context"]["target"] == {"command": ["kubectl"], "argument": "--context"}
    assert "Bash(git push origin main:*)" in gateway["client_permissions"]["deny"]
    assert VIRTUAL_KEY not in response.text


@pytest.mark.asyncio
async def test_the_policy_summary_names_default_budgets_and_an_unclassified_workspace(client, db):
    workspace_id = await _workspace(db, None)
    member = await seed_member(db, workspace_id=workspace_id, role="member")
    await db.commit()

    body = (await client.get(_summary(workspace_id), headers=await _bearer(member))).json()

    assert body["classification"] == {"effective": None, "source": "unset"}
    assert body["rules"] is None and body["connectors"] is None
    assert body["seat"]["reason"] == "seat_classification_unresolved"
    assert body["budgets"]["per_user_daily_usd"] == {"value_usd": 200.0, "source": "default"}
    assert body["budgets"]["session_cost_limit_usd"]["source"] in {"default", "global"}
