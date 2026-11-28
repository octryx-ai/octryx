"""Budget enforcement picks the weekly or monthly limit by reset period, blocks only on the usage of its own agent chain or flow, and usage events keep their attribution."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.tool import BudgetLimitExceededError
from app.models import UsageEvent
from app.models.runtime.budget import (
    RESET_PERIOD_MONTHLY,
    RESET_PERIOD_WEEKLY,
)
from app.services.budget.enforcement import enforce_budget_limits
from tests.quota_governance_support import _add_usage, _make_policy, _make_session, _uid

# ── reset period window selection ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_weekly_policy_uses_weekly_limit(db: AsyncSession, auth_user):
    sess = await _make_session(db, user_id=str(auth_user.id))
    await _make_policy(
        db,
        user_id=str(auth_user.id),
        reset_period=RESET_PERIOD_WEEKLY,
        weekly_token_limit=1000,   # tight weekly limit
        daily_token_limit=None,    # daily limit not set
    )
    await _add_usage(db, session_id=sess.id, user_id=str(auth_user.id),
                     tokens_in=900, tokens_out=0)

    with pytest.raises(BudgetLimitExceededError) as exc_info:
        await enforce_budget_limits(
            db,
            session_id=sess.id,
            user_id=str(auth_user.id),
            project_id=None,
            runtimes=[],
            messages=[{"role": "user", "content": "hello"}],
            max_completion_tokens=200,
            approx_chars_per_token=4,
        )
    assert exc_info.value.metric_name == "tokens"


@pytest.mark.asyncio
async def test_monthly_policy_uses_monthly_limit(db: AsyncSession, auth_user):
    sess = await _make_session(db, user_id=str(auth_user.id))
    await _make_policy(
        db,
        user_id=str(auth_user.id),
        reset_period=RESET_PERIOD_MONTHLY,
        monthly_token_limit=500,
        daily_token_limit=None,
    )
    await _add_usage(db, session_id=sess.id, user_id=str(auth_user.id),
                     tokens_in=490, tokens_out=0)

    with pytest.raises(BudgetLimitExceededError) as exc_info:
        await enforce_budget_limits(
            db,
            session_id=sess.id,
            user_id=str(auth_user.id),
            project_id=None,
            runtimes=[],
            messages=[{"role": "user", "content": "x" * 40}],
            max_completion_tokens=50,
            approx_chars_per_token=4,
        )
    assert exc_info.value.metric_name == "tokens"


# ── agent_chain scoped enforcement ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_chain_policy_blocks_on_chain_usage(db: AsyncSession, auth_user):
    chain_id = _uid()
    sess = await _make_session(db, user_id=str(auth_user.id))
    await _make_policy(
        db,
        name="chain-policy",
        agent_chain_id=chain_id,
        daily_request_limit=2,
    )
    for _ in range(2):
        await _add_usage(db, session_id=sess.id, user_id=str(auth_user.id),
                         agent_chain_id=chain_id)

    with pytest.raises(BudgetLimitExceededError):
        await enforce_budget_limits(
            db,
            session_id=sess.id,
            user_id=str(auth_user.id),
            project_id=None,
            runtimes=[],
            messages=[{"role": "user", "content": "test"}],
            max_completion_tokens=10,
            approx_chars_per_token=4,
            agent_chain_id=chain_id,
        )


@pytest.mark.asyncio
async def test_agent_chain_policy_does_not_block_other_chain(db: AsyncSession, auth_user):
    chain_id = _uid()
    other_chain_id = _uid()
    sess = await _make_session(db, user_id=str(auth_user.id))
    await _make_policy(
        db,
        name="chain-policy",
        agent_chain_id=chain_id,
        daily_request_limit=2,
    )
    for _ in range(2):
        await _add_usage(db, session_id=sess.id, user_id=str(auth_user.id),
                         agent_chain_id=chain_id)

    await enforce_budget_limits(
        db,
        session_id=sess.id,
        user_id=str(auth_user.id),
        project_id=None,
        runtimes=[],
        messages=[{"role": "user", "content": "test"}],
        max_completion_tokens=10,
        approx_chars_per_token=4,
        agent_chain_id=other_chain_id,
    )


# ── flow scoped enforcement ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flow_policy_blocks_on_flow_usage(db: AsyncSession, auth_user):
    flow_id = _uid()
    sess = await _make_session(db, user_id=str(auth_user.id))
    await _make_policy(
        db,
        name="flow-policy",
        flow_definition_id=flow_id,
        daily_token_limit=200,
    )
    await _add_usage(db, session_id=sess.id, user_id=str(auth_user.id),
                     tokens_in=190, tokens_out=0, flow_definition_id=flow_id)

    with pytest.raises(BudgetLimitExceededError) as exc_info:
        await enforce_budget_limits(
            db,
            session_id=sess.id,
            user_id=str(auth_user.id),
            project_id=None,
            runtimes=[],
            messages=[{"role": "user", "content": "x" * 40}],
            max_completion_tokens=50,
            approx_chars_per_token=4,
            flow_definition_id=flow_id,
        )
    assert exc_info.value.metric_name == "tokens"


# ── usage attribution columns ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_usage_event_stores_attribution(db: AsyncSession, auth_user):
    from app.agent.runtime.execution_support import record_usage_event

    sess = await _make_session(db, user_id=str(auth_user.id))
    chain_id = _uid()
    flow_id = _uid()
    await record_usage_event(
        db=db,
        session_id=sess.id,
        user_id=str(auth_user.id),
        provider="openai",
        model="gpt-4o",
        usage={"prompt_tokens": 100, "completion_tokens": 50},
        agent_chain_id=chain_id,
        flow_definition_id=flow_id,
    )
    event = (
        await db.execute(
            select(UsageEvent)
            .where(UsageEvent.agent_chain_id == chain_id)
            .order_by(UsageEvent.created_at.desc())
        )
    ).scalar_one_or_none()
    assert event is not None
    assert event.agent_chain_id == chain_id
    assert event.flow_definition_id == flow_id
