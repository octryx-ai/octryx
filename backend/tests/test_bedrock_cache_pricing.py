"""Bedrock-direct turns record and price prompt-cache tokens like the gateway path.

A Converse usage payload reports ``inputTokens`` (uncached) plus
``cacheReadInputTokens`` / ``cacheWriteInputTokens``. The usage event stores them
in the gateway's convention (``tokens_in`` uncached, cache tokens in their own
columns) and charges them at the model row's cache pair when the catalog has it.
Without the pair the charge is the one Bedrock turns always had: every prompt
token at the input rate, recorded as such.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.agent.core.execution_support import record_usage_event
from app.agent.providers.bedrock import BedrockClient
from app.models import LLMModel, LLMProvider, Session, UsageEvent, User
from app.services.budget import estimate_runtime_cost
from app.services.provider.bedrock_pricing import reprice_unpriced_bedrock_usage

MODEL_ID = "anthropic.claude-sonnet-4-6"
INPUT_RATE, OUTPUT_RATE, CACHE_READ_RATE, CACHE_WRITE_RATE = 3.0, 15.0, 0.3, 3.75
UNCACHED, OUTPUT, CACHE_READ, CACHE_WRITE = 1000, 200, 4000, 500
# (1000 * 3.0 + 200 * 15.0 + 4000 * 0.3 + 500 * 3.75) / 1e6
CACHE_RATE_COST = Decimal("0.009075")
# (5500 * 3.0 + 200 * 15.0) / 1e6: every prompt token at the input rate.
INPUT_RATE_COST = Decimal("0.019500")


def _converse_usage() -> dict:
    client = BedrockClient(region="eu-central-1")
    response = client._parse_response(
        {
            "output": {"message": {"content": [{"text": "ok"}]}},
            "usage": {
                "inputTokens": UNCACHED,
                "outputTokens": OUTPUT,
                "totalTokens": UNCACHED + OUTPUT + CACHE_READ + CACHE_WRITE,
                "cacheReadInputTokens": CACHE_READ,
                "cacheWriteInputTokens": CACHE_WRITE,
            },
            "metrics": {},
        },
        fallback_model=MODEL_ID,
        prompt_cache_enabled=True,
    )
    return response["usage"]


async def _bedrock_session(db, *, cache_rates: bool) -> tuple[User, Session]:
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    provider = LLMProvider(id=str(uuid.uuid4()), name="bedrock", driver="bedrock_api", is_active=True)
    model = LLMModel(
        id=str(uuid.uuid4()),
        provider_id=provider.id,
        model_id=MODEL_ID,
        pricing_input=INPUT_RATE,
        pricing_output=OUTPUT_RATE,
        pricing_cache_read=CACHE_READ_RATE if cache_rates else None,
        pricing_cache_write=CACHE_WRITE_RATE if cache_rates else None,
        is_active=True,
    )
    session = Session(id=str(uuid.uuid4()), user_id=admin_user.id, status="active")
    db.add_all([provider, model, session])
    await db.commit()
    return admin_user, session


async def _events(db, session_id: str) -> list[UsageEvent]:
    return list((await db.execute(select(UsageEvent).where(UsageEvent.session_id == session_id))).scalars().all())


@pytest.mark.parametrize(
    ("cache_rates", "expected_cost", "expected_status"),
    [
        (True, CACHE_RATE_COST, "priced_cache_rates"),
        (False, INPUT_RATE_COST, "priced_cache_input_rate"),
    ],
)
async def test_bedrock_turn_records_cache_tokens_separately_and_prices_them_from_the_catalog(
    db, cache_rates: bool, expected_cost: Decimal, expected_status: str
) -> None:
    admin_user, session = await _bedrock_session(db, cache_rates=cache_rates)
    usage = _converse_usage()

    await record_usage_event(
        db=db,
        session_id=session.id,
        user_id=admin_user.id,
        provider="bedrock",
        model=MODEL_ID,
        usage=usage,
        driver="bedrock_api",
    )
    await db.commit()

    [event] = await _events(db, session.id)
    assert (event.tokens_in, event.cache_read_tokens, event.cache_creation_tokens) == (
        UNCACHED,
        CACHE_READ,
        CACHE_WRITE,
    )
    # Gateway convention: the cache columns are additional to tokens_in, so the
    # three add up to the prompt count the provider reported.
    assert event.tokens_in + event.cache_read_tokens + event.cache_creation_tokens == usage["prompt_tokens"]
    assert event.tokens_out == OUTPUT
    assert event.cost == expected_cost
    assert event.cost_status == expected_status


async def test_without_cache_rates_the_charge_is_the_input_rate_charge_it_always_was(db) -> None:
    admin_user, session = await _bedrock_session(db, cache_rates=False)
    usage = _converse_usage()

    await record_usage_event(
        db=db, session_id=session.id, user_id=admin_user.id, provider="bedrock", model=MODEL_ID, usage=usage
    )
    await db.commit()

    previous_charge = await estimate_runtime_cost(
        db,
        provider_name="bedrock",
        model_id=MODEL_ID,
        prompt_tokens=usage["prompt_tokens"],
        completion_tokens=usage["completion_tokens"],
    )
    [event] = await _events(db, session.id)
    assert event.cost == previous_charge == INPUT_RATE_COST


async def test_repricing_prices_split_cache_columns_at_the_catalog_cache_rates(db) -> None:
    admin_user, session = await _bedrock_session(db, cache_rates=True)
    split_event = UsageEvent(
        id=str(uuid.uuid4()),
        session_id=session.id,
        user_id=admin_user.id,
        provider="bedrock",
        model=MODEL_ID,
        tokens_in=UNCACHED,
        tokens_out=OUTPUT,
        cache_read_tokens=CACHE_READ,
        cache_creation_tokens=CACHE_WRITE,
        cost=0,
    )
    db.add(split_event)
    await db.commit()

    result = await reprice_unpriced_bedrock_usage(db, model_id=MODEL_ID)

    assert result["events_updated"] == 1
    refreshed = (await db.execute(select(UsageEvent).where(UsageEvent.id == split_event.id))).scalar_one()
    assert refreshed.cost == CACHE_RATE_COST
    assert refreshed.cost_status == "priced_cache_rates"
