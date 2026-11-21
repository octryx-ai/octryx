"""The scopes one agent run executes in (the Product Run and the policy principal)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from ...services.policy_engine.request_principal import policy_principal_scope
from ._engine_product_run import ProductRunScope


@asynccontextmanager
async def run_scope(
    db: AsyncSession, *, session_id: str, origin: str | None, user_id: str | None
) -> AsyncIterator[ProductRunScope]:
    """The turn's Product Run bookkeeping, and the run's user and session as the Cedar principal of every
    enforcement point the turn reaches (model admission, tool admission, remote models)."""
    async with ProductRunScope(db, session_id=session_id, origin=origin) as product_run, \
            policy_principal_scope(user_id, session_id=session_id):
        yield product_run
