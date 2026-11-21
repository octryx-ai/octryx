"""Model catalog: rows, saves mirrored into the gateway alias, derived level lists, sync flags."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.models import AuditLog, LLMModel, LLMProvider, Project, User
from app.services.auth import create_access_token
from app.services.data_classification.policy_matrix import load_classification_policy
from app.services.model_catalog.clearance import cleared_aliases_by_level
from app.services.model_catalog.contract import ModelCatalogError
from app.services.model_catalog.sync import add_alias_for, add_selected, sync_catalog
from app.services.model_catalog.update import AUDIT_ACTION, update_catalog_model
from app.services.model_catalog.views import list_catalog
from app.services.model_gateway.inbound.admission import InboundAdmission, admit_inbound_call
from app.services.policy_engine.baseline import load_baseline
from app.services.secret import set_secret_value
from tests.model_gateway.conftest import ALIAS, GATEWAY_HOST, VIRTUAL_KEY, gateway_provider

ROUTE = "/api/v1/admin/model-catalog"

pytestmark = pytest.mark.asyncio


async def _admin_id(db) -> str:
    return (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()


async def _gateway(db, *, cleared: str | None = "internal", enabled: bool = True) -> tuple[LLMProvider, LLMModel]:
    secret = await set_secret_value(db, tool_name="litellm_gateway", field_name="virtual_key", project_id=None,
                                    value=VIRTUAL_KEY)
    provider = gateway_provider(name=f"litellm-{uuid.uuid4().hex[:6]}", api_key_secret_ref=secret.id,
                                endpoint_url=f"https://{GATEWAY_HOST}")
    db.add(provider)
    await db.flush()
    model = LLMModel(provider_id=provider.id, model_id=ALIAS, display_name="Orion", is_active=enabled,
                     cleared_up_to=cleared)
    db.add(model)
    await db.commit()
    return provider, model


async def _workspace(db, level: str = "internal") -> str:
    project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:8]}", is_active=True,
                      config={"model_policy": {"allowed_aliases": [ALIAS]}, "data_policy": {"classification": level}})
    db.add(project)
    await db.commit()
    return project.id


def _alias(provider: LLMProvider) -> dict:
    return provider.config_json["litellm_gateway"]["aliases"][ALIAS]


async def test_a_new_row_gets_a_stable_catalog_key_prefixed_only_on_collision(db):
    first = LLMProvider(name="alpha", driver="openrouter_api", display_name="Alpha")
    second = LLMProvider(name="beta", driver="openrouter_api", display_name="Beta")
    db.add_all([first, second])
    await db.flush()
    one = LLMModel(provider_id=first.id, model_id="shared-model")
    two = LLMModel(provider_id=second.id, model_id="shared-model")
    db.add(one)
    await db.flush()
    db.add(two)
    await db.commit()

    assert (one.catalog_key, two.catalog_key) == ("shared-model", "beta/shared-model")


async def test_the_list_shows_display_names_usage_and_needs_attention_rows(db):
    provider, model = await _gateway(db)
    orphan = LLMModel(provider_id=provider.id, model_id="no-alias-model", is_active=True)
    db.add(orphan)
    await _workspace(db)
    await db.commit()

    rows = {row["model_id"]: row for row in (await list_catalog(db))["models"]}

    assert rows[ALIAS]["display_name"] == "Orion" and rows[ALIAS]["status"] == "enabled"
    assert rows[ALIAS]["used_by_workspaces"] >= 1 and rows[ALIAS]["provider"]["is_gateway"] is True
    assert rows["no-alias-model"]["status"] == "needs_attention"
    assert {issue["code"] for issue in rows["no-alias-model"]["issues"]} >= {"no_alias", "not_cleared"}


async def test_a_save_writes_the_row_mirrors_the_alias_and_audits_a_clearance_raise(db):
    provider, model = await _gateway(db, cleared="public")
    admin = await _admin_id(db)

    await update_catalog_model(db, model_id=model.id, actor_id=admin, payload={
        "display_name": "Orion Large", "capabilities": {"tools": True, "vision": True, "coding": True},
        "cleared_up_to": "confidential", "approved_data_categories": ["pii"], "temperature": 0.2,
        "max_output_tokens": 4000,
    })
    await db.commit()
    await db.refresh(provider)

    entry = _alias(provider)
    assert (model.display_name, model.cleared_up_to, model.temperature) == ("Orion Large", "confidential", 0.2)
    assert model.capabilities_json["coding"] is True and model.supports_vision is True
    assert entry["data_policy_class"] == "confidential" and entry["approved_data_categories"] == ["pii"]
    assert entry["display_name"] == "Orion Large" and entry["capabilities"]["vision"] is True
    assert entry["model_group"]  # connection keys stay
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == AUDIT_ACTION))).scalars().one()
    assert audit.details["clearance_raise"]["approval"] == "applied_directly"

    await update_catalog_model(db, model_id=model.id, actor_id=admin, payload={"cleared_up_to": None})
    await db.commit()
    await db.refresh(provider)
    assert "data_policy_class" not in _alias(provider)


async def test_a_clearance_save_of_a_row_without_capabilities_json_mirrors_its_supports_flags(db):
    # A clearance PATCH on a row without capabilities_json (as provider sync inserts it) must not write tools=false
    # into the alias: the gateway would refuse the model with capability_not_proven.
    provider, model = await _gateway(db, cleared="public")
    model.capabilities_json = None
    model.supports_tools = True
    model.supports_vision = True
    await db.commit()

    await update_catalog_model(db, model_id=model.id, actor_id=await _admin_id(db),
                               payload={"cleared_up_to": "internal"})
    await db.commit()
    await db.refresh(provider)

    capabilities = _alias(provider)["capabilities"]
    assert capabilities["tools"] is True and capabilities["vision"] is True


@pytest.mark.parametrize("payload", [
    {"cleared_up_to": "secret"}, {"temperature": 3}, {"max_output_tokens": 10}, {"capabilities": {"fast": True}},
    {"approved_data_categories": ["Not A Slug"]}, {"unknown": 1}, {"cost": {"cost_source": "catalog_pricing"}},
])
async def test_an_invalid_save_is_refused_and_changes_nothing(db, payload):
    _provider, model = await _gateway(db)

    with pytest.raises(ModelCatalogError):
        await update_catalog_model(db, model_id=model.id, actor_id=await _admin_id(db), payload=payload)
    assert model.cleared_up_to == "internal" and model.temperature is None


async def test_a_gateway_cost_save_writes_the_alias_contract_and_mirrors_the_row(db):
    provider, model = await _gateway(db)

    await update_catalog_model(db, model_id=model.id, actor_id=await _admin_id(db), payload={
        "cost": {"cost_source": "catalog_pricing", "pricing_input": 2, "pricing_output": 8}})
    await db.commit()
    await db.refresh(provider)

    assert _alias(provider)["cost"] == {"source": "catalog_pricing", "input_per_million_usd": 2.0,
                                        "output_per_million_usd": 8.0}
    assert (model.cost_source, model.pricing_input, model.pricing_output) == ("catalog_pricing", 2.0, 8.0)


async def test_a_direct_model_with_a_governed_price_refuses_a_price_edit(db):
    provider = LLMProvider(name="bedrock", driver="bedrock_api", display_name="Bedrock")
    db.add(provider)
    await db.flush()
    model = LLMModel(provider_id=provider.id, model_id="vega", cost_source="catalog_pricing", pricing_input=1.0)
    db.add(model)
    await db.commit()

    with pytest.raises(ModelCatalogError) as refused:
        await update_catalog_model(db, model_id=model.id, actor_id=await _admin_id(db),
                                   payload={"cost": {"pricing_input": 5}})
    assert refused.value.code == "model_catalog_cost_governed"


async def test_a_direct_model_keeps_an_admin_set_context_window_that_its_listing_lacks(db):
    provider = LLMProvider(name="bedrock", driver="bedrock_api", display_name="Bedrock")
    db.add(provider)
    await db.flush()
    model = LLMModel(provider_id=provider.id, model_id="vega")
    db.add(model)
    await db.commit()
    admin = await _admin_id(db)

    await update_catalog_model(db, model_id=model.id, actor_id=admin, payload={"context_length": 1_000_000})
    await db.commit()
    assert model.context_length == 1_000_000
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == AUDIT_ACTION))).scalars().one()
    assert audit.details["changed_keys"] == ["context_length"]
    assert (audit.details["before"]["context_length"], audit.details["after"]["context_length"]) == (None, 1_000_000)

    for refused_value in (999, 10_000_001, True, "1000000", 1.5e6):
        with pytest.raises(ModelCatalogError) as refused:
            await update_catalog_model(db, model_id=model.id, actor_id=admin, payload={"context_length": refused_value})
        assert refused.value.code == "model_catalog_context_length_invalid"
    assert model.context_length == 1_000_000

    await update_catalog_model(db, model_id=model.id, actor_id=admin, payload={"context_length": None})
    assert model.context_length is None


async def test_a_gateway_model_takes_its_context_window_from_the_gateway_contract(db):
    _provider, model = await _gateway(db)

    with pytest.raises(ModelCatalogError) as refused:
        await update_catalog_model(db, model_id=model.id, actor_id=await _admin_id(db),
                                   payload={"context_length": 200_000})
    assert refused.value.code == "model_catalog_context_length_governed"
    assert model.context_length is None


async def test_a_row_price_the_gateway_contract_does_not_charge_needs_attention(db):
    provider, model = await _gateway(db)
    admin = await _admin_id(db)
    await update_catalog_model(db, model_id=model.id, actor_id=admin, payload={"cost": {
        "cost_source": "catalog_pricing", "pricing_input": 4.4, "pricing_output": 22}})
    await db.commit()
    model.pricing_cache_read, model.pricing_cache_write = 0.22, 5.5  # live drift: row-only cache prices
    await db.commit()
    row = next(r for r in (await list_catalog(db))["models"] if r["model_id"] == ALIAS)
    assert {"code": "cost_drift", "detail": "pricing_cache_read,pricing_cache_write"} in row["issues"]

    await update_catalog_model(db, model_id=model.id, actor_id=admin, payload={"cost": {
        "cost_source": "catalog_pricing", "pricing_input": 4.4, "pricing_output": 22,
        "pricing_cache_read": 0.22, "pricing_cache_write": 5.5}})
    await db.commit()
    row = next(r for r in (await list_catalog(db))["models"] if r["model_id"] == ALIAS)
    assert not any(issue["code"] == "cost_drift" for issue in row["issues"])


async def test_the_level_lists_are_derived_from_clearance_for_admission_and_cedar(db):
    _provider, model = await _gateway(db, cleared="internal")
    workspace = await _workspace(db, "confidential")

    derived = await cleared_aliases_by_level(db)
    refused = await admit_inbound_call(db, workspace_id=workspace, alias=ALIAS, declares_tools=False)
    baseline = (await load_baseline(db)).text
    matrix = await load_classification_policy(db)

    assert derived["public"] == derived["internal"] == (ALIAS,) and derived["confidential"] == ()
    assert matrix.rules_for("internal").allowed_model_aliases == (ALIAS,)
    assert not isinstance(refused, InboundAdmission) and refused.reason == "model_alias_not_allowed_for_classification"
    assert "classification:confidential:model-aliases" in baseline

    await update_catalog_model(db, model_id=model.id, actor_id=await _admin_id(db),
                               payload={"cleared_up_to": "confidential"})  # mirrored into the alias
    await db.commit()
    assert isinstance(await admit_inbound_call(db, workspace_id=workspace, alias=ALIAS, declares_tools=False),
                      InboundAdmission)
    model.is_active = False
    await db.commit()
    assert (await cleared_aliases_by_level(db))["public"] == ()


async def test_sync_flags_vanished_proposes_new_and_adds_selected_inactive(db):
    provider, _model = await _gateway(db)
    gone = LLMModel(provider_id=provider.id, model_id="gone-alias", is_active=True,
                    last_synced_at=datetime(2026, 1, 1))
    db.add(gone)
    config = dict(provider.config_json)
    section = dict(config["litellm_gateway"])
    section["aliases"] = {**section["aliases"], "new-alias": {"model_group": "group-x", "context_limit": 1000}}
    config["litellm_gateway"] = section
    provider.config_json = config
    await db.commit()
    admin = await _admin_id(db)

    async def _never(*_args, **_kwargs):
        raise AssertionError("the gateway is listed from its alias catalog, without a network call")

    result = await sync_catalog(db, build_kwargs=_never, actor_id=admin)
    await db.commit()
    created = await add_selected(db, selected=[{"provider_id": provider.id, "model_id": "new-alias"}],
                                 build_kwargs=_never, actor_id=admin)
    await db.commit()

    assert [item["model_id"] for item in result["new"]] == ["new-alias"]
    assert [item["id"] for item in result["gone"]] == [gone.id] and gone.upstream_gone_at is not None
    assert gone.id in {item["id"] for item in result["gateway_without_alias"]}
    added = await db.get(LLMModel, created[0])
    assert added.is_active is False and added.catalog_key == "new-alias"

    await add_alias_for(db, model_id=gone.id, actor_id=admin)
    await db.commit()
    await db.refresh(provider)
    assert provider.config_json["litellm_gateway"]["aliases"]["gone-alias"]["model_group"] == "gone-alias"
    assert gone.is_active is False


async def test_the_api_is_for_platform_admins(client, db):
    _provider, model = await _gateway(db)
    admin = await _admin_id(db)
    headers = {"Authorization": f"Bearer {create_access_token(admin)}"}

    listed = await client.get(ROUTE, headers=headers)
    patched = await client.patch(f"{ROUTE}/models/{model.id}", json={"enabled": False}, headers=headers)
    refused = await client.patch(f"{ROUTE}/models/{model.id}", json={"temperature": 9}, headers=headers)

    assert listed.status_code == 200 and listed.json()["clearance_levels"][-1] == "restricted"
    assert patched.status_code == 200 and patched.json()["enabled"] is False
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "model_catalog_temperature_invalid"
    assert (await client.get(ROUTE)).status_code == 401
