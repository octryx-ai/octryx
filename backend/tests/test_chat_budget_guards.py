"""Budget and session cost guards: warning alerts, default blocks and blocking a chat send before the provider call."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.exceptions.tool import BudgetLimitExceededError
from app.models import BudgetAlert, BudgetPolicy, LLMModel, LLMProvider, Session, UsageEvent, User
from app.services.budget import enforce_budget_limits
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_budget_guard_emits_warning_alert_before_threshold_block(db):
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    policy = BudgetPolicy(
        id=str(uuid.uuid4()),
        name="Warning threshold",
        user_id=admin_user.id,
        daily_token_limit=100,
        warn_at_percent=80,
        block_at_percent=100,
        is_active=True,
    )
    db.add(policy)
    await db.commit()

    await enforce_budget_limits(
        db,
        session_id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=None,
        runtimes=[],
        messages=[{"role": "user", "content": "a" * 320}],
        max_completion_tokens=0,
        approx_chars_per_token=4,
    )

    alerts = (
        (
            await db.execute(
                select(BudgetAlert).where(
                    BudgetAlert.policy_id == policy.id,
                    BudgetAlert.metric_name == "tokens",
                    BudgetAlert.threshold_level == "warning",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(alerts) == 1
    assert alerts[0].percent_used >= 80


@pytest.mark.asyncio
async def test_default_session_cost_guard_blocks_without_budget_policy(db, monkeypatch):
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin_user.id, status="active")
    provider = LLMProvider(id=str(uuid.uuid4()), name="bedrock", driver="bedrock_api", display_name="Bedrock", is_active=True)
    model = LLMModel(
        id=str(uuid.uuid4()),
        provider_id=provider.id,
        model_id="expensive-model",
        pricing_input=2.0,
        pricing_output=2.0,
        is_active=True,
    )
    db.add_all(
        [
            session,
            provider,
            model,
            UsageEvent(
                id=str(uuid.uuid4()),
                session_id=session.id,
                user_id=admin_user.id,
                provider="bedrock",
                model="expensive-model",
                tokens_in=1,
                tokens_out=0,
                cost=Decimal("0.000002"),
            ),
        ]
    )
    await db.commit()
    monkeypatch.setenv("OCTRYX_AGENT_SESSION_COST_LIMIT_USD", "0.000003")

    with pytest.raises(BudgetLimitExceededError) as exc:
        await enforce_budget_limits(
            db,
            session_id=session.id,
            user_id=admin_user.id,
            project_id=None,
            runtimes=[{"provider_name": "bedrock", "model": "expensive-model"}],
            messages=[{"role": "user", "content": "x"}],
            max_completion_tokens=0,
            approx_chars_per_token=4,
        )

    assert exc.value.policy_name == "Default agent session cost guard"


