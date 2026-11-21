"""Shared policy, usage and session builders for the cost quota and budget governance tests."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BudgetPolicy, UsageEvent
from app.models.session.session import Session as ChatSession


def _uid() -> str:
    return str(uuid.uuid4())


async def _make_policy(db: AsyncSession, *, name: str = "test-policy", **kwargs) -> BudgetPolicy:
    """Directly insert a BudgetPolicy bypassing service validation for test fixtures."""
    policy = BudgetPolicy(
        id=_uid(),
        name=name,
        warn_at_percent=80,
        block_at_percent=100,
        is_active=True,
        **kwargs,
    )
    db.add(policy)
    await db.commit()
    await db.refresh(policy)
    return policy


async def _add_usage(db: AsyncSession, *, session_id: str, user_id: str,
                     tokens_in: int = 100, tokens_out: int = 50,
                     cost: Decimal = Decimal("0.001"),
                     agent_chain_id: str | None = None,
                     flow_definition_id: str | None = None,
                     provider: str = "openai", model: str = "gpt-4o") -> UsageEvent:
    event = UsageEvent(
        id=_uid(),
        session_id=session_id,
        user_id=user_id,
        provider=provider,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost=cost,
        agent_chain_id=agent_chain_id,
        flow_definition_id=flow_definition_id,
    )
    db.add(event)
    await db.commit()
    return event


async def _make_session(db: AsyncSession, *, user_id: str) -> ChatSession:
    s = ChatSession(id=_uid(), user_id=user_id, project_id=None, status="active")
    db.add(s)
    await db.commit()
    return s
