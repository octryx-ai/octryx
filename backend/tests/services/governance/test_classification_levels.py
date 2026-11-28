"""Classification levels are data. Admins add a level through a governed version; ranks are
stored and gapped; a level in use cannot be retired; a level without models refuses every model."""

from __future__ import annotations

import uuid

import pytest

from app.models import Project
from app.services.data_classification.levels import (
    BUILTIN_REGISTRY,
    LevelDef,
    LevelRegistry,
    level_registry,
    rank_between,
    reset_level_registry,
    set_level_registry,
)
from app.services.data_classification.policy_matrix import load_classification_policy
from app.services.data_classification.policy_rules import default_rules
from app.services.governance.approval_rule import APPROVAL_RULE_CONFIG_KEY
from app.services.model_gateway.data_policy.classification import (
    DATA_CLASSIFICATION_ORDER,
    MODEL_DATA_POLICY_CLASSES,
    WorkspaceDataClassification,
    classification_rank,
)
from app.services.model_gateway.data_policy.gate import data_policy_decision
from app.services.policy_engine.translator import level_policies
from app.services.system_config.values import set_system_config_value
from tests.policy_engine_support import bearer, make_user

ROUTE = "/api/v1/admin/data-classification/policy"
PARTNER = {"key": "partner_shared", "rank": 350, "label": "Partner shared", "color": "custom",
           "description": "Shared with named partners under contract.", "models_allowed": True}


@pytest.fixture(autouse=True)
def _registry():
    reset_level_registry()
    yield
    reset_level_registry()


def _catalog(*extra: dict) -> list[dict]:
    return [level.to_dict() for level in BUILTIN_REGISTRY.levels] + list(extra)


async def _publish(client, db, admin: str, body: dict) -> dict:
    await set_system_config_value(db, key=APPROVAL_RULE_CONFIG_KEY, value="single_admin")
    await db.commit()
    saved = await client.put(f"{ROUTE}/draft", json=body, headers=bearer(admin))
    assert saved.status_code == 200, saved.text
    version = (await client.post(f"{ROUTE}/draft/submit", json={}, headers=bearer(admin))).json()["draft"]["version"]
    published = await client.post(f"{ROUTE}/versions/{version}/approve", headers=bearer(admin))
    assert published.status_code == 200, published.text
    return published.json()


def test_the_builtins_keep_their_order_with_stored_gapped_ranks():
    assert list(DATA_CLASSIFICATION_ORDER) == ["public", "internal", "confidential", "restricted", "secret"]
    assert [classification_rank(level) for level in DATA_CLASSIFICATION_ORDER] == [100, 200, 300, 400, 500]
    assert set(MODEL_DATA_POLICY_CLASSES) == {"public", "internal", "confidential", "restricted"}
    assert rank_between(BUILTIN_REGISTRY.get("confidential"), BUILTIN_REGISTRY.get("restricted")) == 350
    assert rank_between(BUILTIN_REGISTRY.get("secret"), None) == 600
    assert rank_between(LevelDef("a", 10, "A"), LevelDef("b", 11, "B")) is None, "no integer fits"


@pytest.mark.asyncio
async def test_an_admin_adds_a_level_between_two_levels_and_existing_ranks_do_not_move(client, db):
    admin = await make_user(db, admin=True)
    restricted_rules = (await load_classification_policy(db)).rules_for("restricted").to_dict()
    restricted_rules.pop("allowed_model_aliases")
    body = await _publish(client, db, admin, {
        "levels": [{"level": "partner_shared", "rules": restricted_rules}], "default_level": None,
        "level_catalog": _catalog(PARTNER)})
    assert body["versions"][0]["changes"][0]["text"] == "Level “Partner shared” added (rank 350)"

    assert list(DATA_CLASSIFICATION_ORDER)[3] == "partner_shared"
    assert classification_rank("partner_shared") == 350 and classification_rank("restricted") == 400
    read = (await client.get(ROUTE, headers=bearer(admin))).json()
    partner = next(item for item in read["levels"] if item["level"] == "partner_shared")
    assert partner["label"] == "Partner shared" and partner["rank"] == 350 and partner["builtin"] is False
    assert partner["rules"]["seat_allowed"] is False, "rules copied from the next stricter level"

    project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:6]}", is_active=True, config={})
    db.add(project)
    await db.commit()
    classified = await client.put(f"/api/v1/workspaces/{project.id}/data-classification",
                                  json={"classification": "partner_shared"}, headers=bearer(admin))
    assert classified.status_code == 200, classified.text

    retire = await client.put(f"{ROUTE}/draft", json={"levels": [], "default_level": None, "level_catalog": _catalog()},
                              headers=bearer(admin))
    assert retire.status_code == 422
    detail = retire.json()["detail"]
    assert detail["code"] == "classification_level_in_use"
    assert {"kind": "workspace", "id": project.id, "name": project.name} in detail["references"]


@pytest.mark.asyncio
async def test_a_catalog_cannot_drop_a_builtin_move_a_rank_or_reuse_a_key(client, db):
    admin = await make_user(db, admin=True)
    without_secret = [level for level in _catalog() if level["key"] != "secret"]
    moved = [{**level, "rank": 250} if level["key"] == "confidential" else level for level in _catalog()]
    cases = [
        (without_secret, "classification_level_builtin_changed"),
        (moved, "classification_level_rank_changed"),
        (_catalog(PARTNER, {**PARTNER, "rank": 360}), "classification_level_key_duplicate"),
        (_catalog({**PARTNER, "key": "Partner"}), "classification_level_key_invalid"),
        (_catalog({**PARTNER, "rank": 300}), "classification_level_rank_invalid"),
    ]
    for catalog, code in cases:
        refused = await client.put(f"{ROUTE}/draft", json={"levels": [], "level_catalog": catalog}, headers=bearer(admin))
        assert refused.status_code == 422 and refused.json()["detail"]["code"] == code, (code, refused.text)
    relabelled = [{**level, "label": "Top secret"} if level["key"] == "secret" else level for level in _catalog()]
    saved = await client.put(f"{ROUTE}/draft", json={"levels": [], "level_catalog": relabelled}, headers=bearer(admin))
    assert saved.status_code == 200 and saved.json()["draft"]["changes"][0]["rule"] == "level_changed"


def test_a_level_without_models_refuses_a_model_cleared_above_it_and_generates_its_forbid():
    vault = LevelDef("vault", 350, "Vault", models_allowed=False)
    set_level_registry(LevelRegistry([*BUILTIN_REGISTRY.levels, vault]))
    assert "vault" not in MODEL_DATA_POLICY_CLASSES
    decision = data_policy_decision(WorkspaceDataClassification("vault", "project_config", ""), "restricted")
    assert decision.allowed is False and decision.reason == "data_policy_class_insufficient"
    assert data_policy_decision(WorkspaceDataClassification("confidential", "project_config", ""), "restricted").allowed
    ids = [item.policy_id for item in level_policies("vault", default_rules("vault"))]
    assert "classification:vault:no-models" in ids and "classification:vault:no-remote-models" in ids
    assert not [item for item in level_policies("secret", default_rules("secret")) if "no-models" in item.policy_id], \
        "the top level needs no extra forbid: nothing is cleared above it"
    assert level_registry().get("vault") == vault
