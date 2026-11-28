"""Company models in the Claude Code ``/model`` picker."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.services.agent_gateway.policy_keys import AgentGatewayPolicyError
from app.services.agent_gateway.policy_normalize import normalize_agent_gateway_policy
from app.services.agent_gateway.seat_policy_keys import BASELINE_SEAT_MODELS
from app.services.model_gateway.inbound.model_listing import PickerModel, company_alias, list_page
from app.services.model_gateway.inbound.seat_company import governed_headers
from app.services.model_gateway.litellm.alias_catalog import resolve_alias_admission
from app.services.policy_engine.shadow import decision_counters
from tests.model_gateway.inbound_model_picker_support import MODELS, OPT_IN, SECOND, _alias, _ids, _workspace
from tests.policy_engine_support import use_custom_policies

from .conftest import ALIAS, MODEL_GROUP, gateway_config

POLICY = "/api/v1/agent-gateway/client-policy"


@pytest.mark.asyncio
async def test_the_governed_route_lists_exactly_the_aliases_a_tool_call_would_be_admitted_for(client, db):
    _workspace_id, gateway = await _workspace(db, policy=None)

    response = await client.get(MODELS, params={"limit": 1000}, headers=gateway)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert _ids(payload) == [ALIAS, SECOND]
    assert payload["data"][0] == {"type": "model", "id": ALIAS, "display_name": "General model",
                                  "description": "Company model through Octryx, billed to the Workspace budget",
                                  "source": "company"}
    assert payload["data"][1]["display_name"] == SECOND
    assert (payload["has_more"], payload["first_id"], payload["last_id"]) == (False, ALIAS, SECOND)
    counters = decision_counters()["model_admission"]
    assert counters["match"] >= 4 and counters["mismatch"] == counters["error"] == 0


@pytest.mark.asyncio
async def test_an_alias_two_providers_list_is_not_offered(client, db):
    _workspace_id, gateway = await _workspace(db, policy=None, second_provider={SECOND: _alias("second-group")})

    response = await client.get(MODELS, params={"limit": 1000}, headers=gateway)

    assert _ids(response.json()) == [ALIAS]


@pytest.mark.asyncio
async def test_the_list_needs_the_gateway_identity_and_a_valid_query(client, db):
    _workspace_id, gateway = await _workspace(db, policy=None)

    assert (await client.get(MODELS)).status_code == 401
    assert (await client.get(MODELS, headers={**gateway, "x-octryx-workspace": str(uuid.uuid4())})
            ).status_code == 403
    bad = await client.get(MODELS, params={"limit": 0}, headers=gateway)
    assert bad.status_code == 400 and "model_list_query_invalid" in bad.json()["error"]["message"]
    page = (await client.get(MODELS, params={"limit": 1}, headers=gateway)).json()
    assert (_ids(page), page["has_more"]) == ([ALIAS], True)
    rest = (await client.get(MODELS, params={"after_id": ALIAS}, headers=gateway)).json()
    assert (_ids(rest), rest["has_more"]) == ([SECOND], False)


@pytest.mark.asyncio
async def test_cedar_call_model_decides_per_alias_in_the_listing(client, db):
    _workspace_id, gateway = await _workspace(db, policy=None)
    use_custom_policies(f'@id("no-second")\nforbid (principal, action == Action::"call_model", '
                        f'resource == ModelAlias::"{SECOND}");', mode="enforce")

    response = await client.get(MODELS, params={"limit": 1000}, headers=gateway)

    assert _ids(response.json()) == [ALIAS]


def test_list_paging_follows_the_anthropic_shape():
    models = [PickerModel(f"m{index}", f"m{index}", "company", "") for index in range(5)]
    assert _ids(list_page(models, {"limit": "2", "before_id": "m4"})) == ["m2", "m3"]
    assert list_page(models, {"limit": "2", "before_id": "m4"})["has_more"] is True
    assert list_page(models, {"limit": "5", "before_id": "m4"})["has_more"] is False
    assert list_page(models, {"limit": "2", "before_id": "m2"})["has_more"] is False
    assert list_page(models, {"limit": "5"})["has_more"] is False
    assert list_page(models, {"limit": "3", "after_id": "m1"})["has_more"] is False
    assert list_page(models, {"limit": "1001"}) is None
    assert list_page(models, {"after_id": "unknown"}) is None
    assert list_page(models, {"after_id": "m1", "before_id": "m3"}) is None
    assert list_page([], {})["first_id"] is None


def test_a_company_id_names_its_alias_exactly():
    assert company_alias("company/octryx-x") == "octryx-x"
    assert company_alias("company/") is None
    assert company_alias("company/ octryx-x") is None
    assert company_alias("company/octryx-x ") is None
    assert company_alias("Company/octryx-x") is None
    assert company_alias("octryx-x") is None


def test_a_display_name_is_optional_and_bounded():
    def admitted(display_name: Any) -> Any:
        return resolve_alias_admission(ALIAS, gateway_config(aliases={ALIAS: _alias(MODEL_GROUP,
                                                                                     display_name=display_name)}))

    assert admitted("  Opus (company)  ").entry.display_name == "Opus (company)"
    for invalid in ("", "x" * 81, "line\nbreak", 7):
        assert admitted(invalid).denial_reason == "alias_display_name_invalid"
    plain = resolve_alias_admission(ALIAS, gateway_config(aliases={ALIAS: _alias(MODEL_GROUP)}))
    assert plain.entry.display_name == ""


@pytest.mark.asyncio
async def test_the_client_policy_carries_both_pickers(client, db):
    _workspace_id, gateway = await _workspace(db, policy=OPT_IN)

    models = (await client.get(POLICY, headers=gateway)).json()["models"]

    assert [row["id"] for row in models["governed"]] == [ALIAS, SECOND]
    assert [row["id"] for row in models["seat"]] == [*BASELINE_SEAT_MODELS, f"company/{ALIAS}", f"company/{SECOND}"]
    assert models["seat_allows_governed_models"] is True


@pytest.mark.asyncio
async def test_without_the_opt_in_the_client_policys_seat_picker_has_subscription_models_only(client, db):
    _workspace_id, gateway = await _workspace(db, policy={"seat_mode": "allowed"})

    models = (await client.get(POLICY, headers=gateway)).json()["models"]

    assert [row["id"] for row in models["seat"]] == [*BASELINE_SEAT_MODELS]
    assert models["seat_allows_governed_models"] is False


@pytest.mark.asyncio
async def test_the_client_policy_offers_no_seat_picker_where_seat_is_forbidden(client, db):
    _workspace_id, gateway = await _workspace(db, policy={"seat_mode": "forbidden", "seat_allows_governed_models": True})

    models = (await client.get(POLICY, headers=gateway)).json()["models"]

    assert models["seat"] == [] and models["seat_allows_governed_models"] is False
    assert [row["id"] for row in models["governed"]] == [ALIAS, SECOND]


def test_the_opt_in_is_a_validated_flag_defaulting_to_off():
    assert normalize_agent_gateway_policy({"seat_allows_governed_models": True}) == {
        "seat_allows_governed_models": True}
    with pytest.raises(AgentGatewayPolicyError) as error:
        normalize_agent_gateway_policy({"seat_allows_governed_models": "yes"})
    assert error.value.reason == "invalid_flag"


def test_the_governed_headers_drop_only_the_subscription_capability():
    assert governed_headers({"anthropic-version": "2023-06-01", "anthropic-beta": "oauth-2025-04-20"}) == {
        "anthropic-version": "2023-06-01"}
    assert governed_headers({"anthropic-beta": " a-1 , oauth-x,b-2", "authorization": "Bearer t",
                             "x-claude-code-session-id": "s-1", "x-api-key": "k"}) == {
        "anthropic-beta": "a-1,b-2", "x-claude-code-session-id": "s-1"}
