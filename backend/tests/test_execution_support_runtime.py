"""``record_usage_event`` persistence behaviour, independent of how cost is attributed."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

import app.agent.runtime.execution_support as execution_support_module
from app.models import UsageEvent, User
from app.services.budget import UsageCostAttribution


def _attribution(cost: str) -> UsageCostAttribution:
    return UsageCostAttribution(
        provider="openai",
        model="model",
        tokens_in=0,
        tokens_out=0,
        effective_tokens_in=0,
        cost=Decimal(cost),
        status="test_fixed_cost",
    )


@pytest.mark.asyncio
async def test_record_usage_event_swallows_cost_computation_value_error(db, monkeypatch):
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    async def fake_attribution(*args, **kwargs):
        raise ValueError("bad usage payload")

    monkeypatch.setattr(execution_support_module, "compute_usage_event_cost_attribution", fake_attribution)

    await execution_support_module.record_usage_event(
        db=db,
        session_id=str(uuid.uuid4()),
        user_id=admin_user.id,
        provider="openai",
        model="gpt-test-runtime",
        usage={"prompt_tokens": 10, "completion_tokens": 5},
    )

    rows = (await db.execute(select(UsageEvent).where(UsageEvent.model == "gpt-test-runtime"))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_record_usage_event_uses_active_db_session_without_opening_nested_session(db, monkeypatch):
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    async def fake_attribution(*args, **kwargs):
        return _attribution("1.25")

    def fail_async_session_factory():
        raise AssertionError("nested usage session should not be opened when db is provided")

    monkeypatch.setattr(execution_support_module, "compute_usage_event_cost_attribution", fake_attribution)
    monkeypatch.setattr(execution_support_module, "async_session_factory", fail_async_session_factory)

    await execution_support_module.record_usage_event(
        db=db,
        session_id=str(uuid.uuid4()),
        user_id=admin_user.id,
        provider="openai",
        model="gpt-test-inline-session",
        usage={"prompt_tokens": 12, "completion_tokens": 6},
    )

    rows = (await db.execute(select(UsageEvent).where(UsageEvent.model == "gpt-test-inline-session"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].tokens_in == 12
    assert rows[0].tokens_out == 6


@pytest.mark.asyncio
async def test_record_usage_event_records_bedrock_cache_tokens_in_their_own_columns(db, monkeypatch):
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    async def fake_attribution(*args, **kwargs):
        return _attribution("1.25")

    monkeypatch.setattr(execution_support_module, "compute_usage_event_cost_attribution", fake_attribution)

    await execution_support_module.record_usage_event(
        db=db,
        session_id=str(uuid.uuid4()),
        user_id=admin_user.id,
        provider="bedrock",
        model="anthropic.claude-sonnet-4-6",
        usage={
            "prompt_tokens": 123,
            "completion_tokens": 45,
            "inputTokens": 123,
            "cacheReadInputTokens": 12,
            "cacheWriteInputTokens": 3,
        },
    )

    rows = (
        await db.execute(select(UsageEvent).where(UsageEvent.model == "anthropic.claude-sonnet-4-6"))
    ).scalars().all()
    assert len(rows) == 1
    # Gateway convention: uncached input in tokens_in, cache reads and writes additional.
    assert (rows[0].tokens_in, rows[0].cache_read_tokens, rows[0].cache_creation_tokens) == (123, 12, 3)
    assert rows[0].tokens_out == 45
