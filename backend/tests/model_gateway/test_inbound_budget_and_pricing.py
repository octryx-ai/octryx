"""Contract: the octryx-claude daily budget, cache-aware pricing and the wired secret detector."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Session, UsageEvent, User
from app.services.agent_gateway.contract import GATEWAY_EXTERNAL_SOURCE, SESSION_KEY_METADATA
from app.services.agent_gateway.daily_budget import utc_day_window
from app.services.agent_gateway.policy_keys import AgentGatewayPolicyError
from app.services.agent_gateway.policy_normalize import normalize_agent_gateway_policy
from app.services.model_gateway.inbound.transcript_cost import usage_cost
from app.services.model_gateway.litellm.alias_catalog import resolve_alias_admission
from app.time_utils import utc_now

from .conftest import ALIAS, alias_with_cost
from .inbound_gateway_support import gateway_setup  # noqa: F401 - fixture
from .test_inbound_anthropic_gateway import ROUTE, _request_body


async def _spend_today(db, amount: str) -> None:
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=user.id,
        agent_type="external_agent",
        status="completed",
        metadata_={"external_source": GATEWAY_EXTERNAL_SOURCE, SESSION_KEY_METADATA: str(uuid.uuid4())},
    )
    db.add(session)
    db.add(UsageEvent(session_id=session.id, user_id=user.id, provider="litellm", model=ALIAS, cost=Decimal(amount)))
    await db.commit()


async def test_an_exhausted_daily_budget_is_refused_before_dispatch(client, db, gateway_setup):  # noqa: F811
    fake, build = gateway_setup
    headers = await build()
    await _spend_today(db, "200.00")  # the baseline policy's 200 USD per user and UTC day (defaults audit #5)

    response = await client.post(ROUTE, json=_request_body(), headers=headers)

    assert response.status_code == 403
    assert response.headers["x-octryx-gateway-state"] == "denied"
    assert response.headers["x-octryx-gateway-reason"] == "gateway_daily_budget_exhausted"
    assert "200.00 USD" in response.json()["error"]["message"]
    assert fake.requests == []


async def test_source_code_that_only_names_secrets_is_dispatched(client, gateway_setup):  # noqa: F811
    fake, build = gateway_setup
    headers = await build()

    response = await client.post(
        ROUTE, json=_request_body(newest_text="password = settings.db_password\ntoken: str = ''"), headers=headers
    )

    assert response.status_code == 200, response.text
    assert len(fake.requests) == 1


def test_cache_tokens_are_priced_at_the_declared_cache_rates():
    config = alias_with_cost(
        {
            "source": "catalog_pricing",
            "input_per_million_usd": 2.0,
            "output_per_million_usd": 10.0,
            "cache_read_per_million_usd": 0.2,
            "cache_write_per_million_usd": 2.5,
        }
    )
    entry = resolve_alias_admission(ALIAS, config).entry
    usage = {"input_tokens": 100, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 10000, "output_tokens": 50}

    cost = usage_cost(entry, usage)

    # (100 * 2.0 + 1000 * 2.5 + 10000 * 0.2 + 50 * 10.0) / 1e6
    assert cost.cost == Decimal("0.0052")
    assert cost.cost_status == "catalog_pricing"


def test_a_half_declared_cache_rate_refuses_the_alias():
    config = alias_with_cost(
        {"source": "catalog_pricing", "input_per_million_usd": 2.0, "output_per_million_usd": 10.0,
         "cache_read_per_million_usd": 0.2}
    )
    assert resolve_alias_admission(ALIAS, config).entry is None


def test_session_budget_validation_and_utc_window():
    assert normalize_agent_gateway_policy({"session_budget": {"per_user_daily_usd": 50}}) == {
        "session_budget": {"per_user_daily_usd": 50.0}
    }
    with pytest.raises(AgentGatewayPolicyError):
        normalize_agent_gateway_policy({"session_budget": {"per_user_daily_usd": 0}})
    start, end = utc_day_window(datetime(2026, 9, 30, 17, 5))
    assert (start, end) == (datetime(2026, 9, 30), datetime(2026, 10, 1))
    assert utc_day_window(utc_now())[0] <= utc_now().replace(tzinfo=None)
