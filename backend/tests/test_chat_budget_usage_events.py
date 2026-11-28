"""Usage event cost attribution and recording usage events with retries and request ids."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.exc import OperationalError

import app.agent.runtime.execution_support as execution_support_module
from app.models import LLMModel, LLMProvider
from app.services.budget import compute_usage_event_cost_attribution
from app.services.request_context import reset_current_request_id, set_current_request_id


@pytest.mark.asyncio
async def test_compute_usage_event_cost_attribution_reports_priced_generic_usage(db):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="OpenRouter Pricing",
        is_global=True,
        is_active=True,
    )
    model = LLMModel(
        id=str(uuid.uuid4()),
        provider_id=provider.id,
        model_id="openai/gpt-priced",
        pricing_input=2.0,
        pricing_output=8.0,
        is_active=True,
    )
    db.add_all([provider, model])
    await db.commit()

    attribution = await compute_usage_event_cost_attribution(
        db,
        provider="openrouter",
        model="openai/gpt-priced",
        tokens_in=1000,
        tokens_out=500,
        usage={},
    )

    assert attribution.status == "priced"
    assert attribution.pricing_input == Decimal("2")
    assert attribution.pricing_output == Decimal("8")
    assert attribution.cost == Decimal("0.006000")


@pytest.mark.asyncio
async def test_compute_usage_event_cost_attribution_reports_missing_pricing(db):
    attribution = await compute_usage_event_cost_attribution(
        db,
        provider="openrouter",
        model="missing/model",
        tokens_in=1000,
        tokens_out=500,
        usage={},
    )

    assert attribution.status == "missing_pricing"
    assert attribution.cost == Decimal("0")


@pytest.mark.asyncio
async def test_compute_usage_event_cost_attribution_prefers_provider_reported_cost(db):
    attribution = await compute_usage_event_cost_attribution(
        db=None,
        provider="bedrock",
        model="anthropic.claude-3-sonnet",
        tokens_in=1000,
        tokens_out=500,
        usage={"cost": "0.1234567"},
    )

    assert attribution.status == "provider_reported_cost"
    assert attribution.cost == Decimal("0.123457")


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_record_usage_event_retries_sqlite_lock_without_failing_run(monkeypatch):
    attempts = {"count": 0, "committed": 0}

    class FakeUsageSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def add(self, _obj):
            return None

        async def commit(self):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise OperationalError("INSERT", {}, Exception("database is locked"))
            attempts["committed"] += 1

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(execution_support_module, "async_session_factory", lambda: FakeUsageSession())
    monkeypatch.setattr(execution_support_module.asyncio, "sleep", fake_sleep)

    await execution_support_module.record_usage_event(
        db=None,
        session_id="session-1",
        user_id="user-1",
        provider="copilot",
        model="gpt-5.3-codex",
        usage={"prompt_tokens": 12, "completion_tokens": 3},
    )

    assert attempts["count"] == 3
    assert attempts["committed"] == 1


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_record_usage_event_persists_request_id(monkeypatch):
    token = set_current_request_id("req-usage-123")
    captured = {"request_ids": []}

    class FakeUsageSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def add(self, obj):
            captured["request_ids"].append(getattr(obj, "request_id", None))

        async def commit(self):
            return None

    monkeypatch.setattr(execution_support_module, "async_session_factory", lambda: FakeUsageSession())
    try:
        await execution_support_module.record_usage_event(
            db=None,
            session_id="session-1",
            user_id="user-1",
            provider="copilot",
            model="gpt-5.3-codex",
            usage={"prompt_tokens": 12, "completion_tokens": 3},
        )
    finally:
        reset_current_request_id(token)

    assert captured["request_ids"] == ["req-usage-123"]
