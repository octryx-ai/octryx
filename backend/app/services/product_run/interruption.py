"""Settle Product Run Attempts whose owning process died (runtime robustness)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.runtime.product_run import (
    RUN_STATE_FAILED,
    TRANSITION_ACTOR_SYSTEM,
    ProductRun,
    ProductRunAttempt,
)
from ..runtime_ownership.process_lease import live_process_ids
from .errors import IllegalProductRunTransitionError, StaleProductRunTransitionError
from .service import ProductRunHandle, transition
from .states import ACTIVE_STATES

END_REASON_INTERRUPTED_BY_RESTART = "interrupted_by_restart"


@dataclass(frozen=True, slots=True)
class SettledAttempt:
    session_id: str
    owner_user_id: str


async def settle_orphaned_attempts(db: AsyncSession) -> list[SettledAttempt]:
    rows = (
        await db.execute(
            select(
                ProductRunAttempt.id,
                ProductRunAttempt.run_id,
                ProductRunAttempt.workspace_id,
                ProductRunAttempt.state,
                ProductRunAttempt.version,
                ProductRunAttempt.owner_process_id,
                ProductRun.version.label("run_version"),
                ProductRun.session_id,
                ProductRun.owner_user_id,
            )
            .join(ProductRun, ProductRun.id == ProductRunAttempt.run_id)
            .where(
                ProductRunAttempt.state.in_(sorted(ACTIVE_STATES)),
                # The run mirrors its latest Attempt; anything else is not movable here.
                ProductRun.state == ProductRunAttempt.state,
                ProductRun.attempt_count == ProductRunAttempt.attempt_number,
            )
        )
    ).all()
    if not rows:
        return []
    live = await live_process_ids(db, (row.owner_process_id for row in rows))
    settled: list[SettledAttempt] = []
    for row in rows:
        if row.owner_process_id in live:
            continue
        handle = ProductRunHandle(
            run_id=row.run_id,
            attempt_id=row.id,
            workspace_id=row.workspace_id,
            state=row.state,
            run_version=row.run_version,
            attempt_version=row.version,
        )
        try:
            await transition(
                db,
                handle,
                to_state=RUN_STATE_FAILED,
                end_reason=END_REASON_INTERRUPTED_BY_RESTART,
                actor=TRANSITION_ACTOR_SYSTEM,
            )
        except (StaleProductRunTransitionError, IllegalProductRunTransitionError):
            # Another sweeper (or a late owner) moved it first; nothing to settle.
            continue
        settled.append(SettledAttempt(session_id=row.session_id, owner_user_id=row.owner_user_id))
    return settled


__all__ = ["END_REASON_INTERRUPTED_BY_RESTART", "SettledAttempt", "settle_orphaned_attempts"]
