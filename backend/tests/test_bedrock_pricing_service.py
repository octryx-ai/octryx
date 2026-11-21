import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import LLMModel, LLMProvider, Session, UsageEvent, User
from app.services.provider.bedrock_pricing import (
    build_bedrock_pricing_index,
    reprice_unpriced_bedrock_usage,
    sync_bedrock_model_pricing,
)


def _on_demand_product(model: str, provider: str, inference_type: str) -> dict:
    return {
        "attributes": {
            "feature": "On-demand Inference",
            "inferenceType": inference_type,
            "model": model,
            "provider": provider,
            "regionCode": "eu-central-1",
        }
    }


def _per_1k_tokens_term(dimension: str, usd: str) -> dict:
    return {"term": {"priceDimensions": {dimension: {"unit": "1K tokens", "pricePerUnit": {"USD": usd}}}}}


def _sample_bedrock_offer() -> dict:
    return {
        "publicationDate": "2026-05-29T22:46:55Z",
        "products": {
            "INPUTSKU": _on_demand_product("Claude 3 Sonnet", "Anthropic", "Input tokens"),
            "OUTPUTSKU": _on_demand_product("Claude 3 Sonnet", "Anthropic", "Output tokens"),
            "NOVA2INPUTSKU": _on_demand_product("Nova 2.0 Lite", "Amazon", "Input tokens"),
            "NOVA2OUTPUTSKU": _on_demand_product("Nova 2.0 Lite", "Amazon", "Output tokens"),
            "NOVA2CACHEINPUTSKU": _on_demand_product("Nova 2.0 Lite", "Amazon", "Prompt cache read input tokens"),
            "NOVA2PRIORITYOUTPUTSKU": _on_demand_product("Nova 2.0 Lite", "Amazon", "Output tokens priority"),
        },
        "terms": {
            "OnDemand": {
                "INPUTSKU": _per_1k_tokens_term("input", "0.0030000000"),
                "OUTPUTSKU": _per_1k_tokens_term("output", "0.0150000000"),
                "NOVA2INPUTSKU": _per_1k_tokens_term("input", "0.0004290000"),
                "NOVA2OUTPUTSKU": _per_1k_tokens_term("output", "0.0035970000"),
                "NOVA2CACHEINPUTSKU": _per_1k_tokens_term("input", "0.0001072500"),
                "NOVA2PRIORITYOUTPUTSKU": _per_1k_tokens_term("output", "0.0062947500"),
            }
        },
    }


def _bedrock_provider() -> LLMProvider:
    return LLMProvider(
        id=str(uuid.uuid4()),
        name="bedrock",
        driver="bedrock_api",
        display_name="AWS Bedrock",
        aws_region="eu-central-1",
        is_global=True,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_bedrock_pricing_sync_updates_only_officially_matched_models(db):
    provider = _bedrock_provider()
    priced_model = LLMModel(
        id=str(uuid.uuid4()),
        provider_id=provider.id,
        model_id="anthropic.claude-3-sonnet-20240229-v1:0",
        display_name="Claude 3 Sonnet",
        is_active=True,
    )
    unknown_model = LLMModel(
        id=str(uuid.uuid4()),
        provider_id=provider.id,
        model_id="anthropic.claude-sonnet-4-6",
        display_name="Claude Sonnet 4.6",
        is_active=True,
    )
    db.add_all([provider, priced_model, unknown_model])
    await db.commit()

    result = await sync_bedrock_model_pricing(db, offer_payload=_sample_bedrock_offer())

    assert result["models_seen"] == 2
    assert result["models_updated"] == 1
    assert result["models_without_official_price"] == 1

    refreshed = await db.get(LLMModel, priced_model.id)
    still_unknown = await db.get(LLMModel, unknown_model.id)
    assert refreshed.pricing_input == 3.0
    assert refreshed.pricing_output == 15.0
    assert still_unknown.pricing_input is None
    assert still_unknown.pricing_output is None


@pytest.mark.asyncio
async def test_unpriced_bedrock_usage_is_repriced_from_the_catalog(db):
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    provider = _bedrock_provider()
    model = LLMModel(
        id=str(uuid.uuid4()),
        provider_id=provider.id,
        model_id="anthropic.claude-3-sonnet-20240229-v1:0",
        pricing_input=3.0,
        pricing_output=15.0,
        is_active=True,
    )
    session = Session(id=str(uuid.uuid4()), user_id=admin_user.id)
    event = UsageEvent(
        id=str(uuid.uuid4()),
        session_id=session.id,
        user_id=admin_user.id,
        provider="bedrock",
        model=model.model_id,
        tokens_in=1000,
        tokens_out=100,
        cost=0,
    )
    db.add_all([provider, model, session, event])
    await db.commit()

    result = await reprice_unpriced_bedrock_usage(db, model_id=model.model_id)

    assert result == {"events_updated": 1, "cost_total": "0.004500"}
    refreshed = (await db.execute(select(UsageEvent).where(UsageEvent.id == event.id))).scalar_one()
    assert refreshed.cost == Decimal("0.004500")


def test_bedrock_pricing_index_parses_input_and_output_prices():
    index = build_bedrock_pricing_index(_sample_bedrock_offer())

    entry = index[("eu-central-1", "claude3sonnet")]
    assert entry.input_per_million == Decimal("3.000000")
    assert entry.output_per_million == Decimal("15.000000")


@pytest.mark.asyncio
async def test_bedrock_pricing_sync_matches_nova_2_lite_offer_model_name(db):
    provider = _bedrock_provider()
    nova = LLMModel(
        id=str(uuid.uuid4()),
        provider_id=provider.id,
        model_id="amazon.nova-2-lite-v1:0",
        display_name="Amazon Nova 2 Lite",
        is_active=True,
    )
    db.add_all([provider, nova])
    await db.commit()

    result = await sync_bedrock_model_pricing(db, offer_payload=_sample_bedrock_offer())

    assert result["models_updated"] == 1
    refreshed = await db.get(LLMModel, nova.id)
    assert refreshed.pricing_input == 0.429
    assert refreshed.pricing_output == 3.597
