"""Run/Attempt identity of one turn for ``turn_execution_summary.v1``.

The identity is resolved *only* through the Product Run stamp on the trace's
execution snapshot (``services/product_run/turn_stamp.py``); the summary never
looks up "the latest run of the session". Closed kinds:

* ``product_run``   - a bound stamp resolved to exactly the stamped run/attempt
  pair, in the trace's own session, owned by the requesting user, in the
  session's Workspace, with the stamped attempt number and origin;
* ``unscoped_turn`` - the turn's session had no resolvable Workspace, so no run
  was opened;
* ``compat_turn``   - no stamp: a caller that runs the agent without a ``run_origin``;
* ``unresolved``    - a malformed stamp, or a bound stamp that does not resolve
  (row missing or deleted, owner/session/Workspace/origin mismatch, run/attempt
  mismatch). A forged snapshot therefore never yields a run, and the kind never
  says *why*, so it cannot probe for foreign rows.

The run and attempt states and the end reason are read from the database at
summary time, never from the stamp. The reserved ``completed`` and ``verifying``
states have no producer; should one ever be stored, it reads as ``unknown``.

Loading is read-only: one owner-scoped SELECT, no writes, no gate evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session as ChatSession
from ...models.runtime.product_run import RUN_END_REASONS, RUN_STATES, ProductRun, ProductRunAttempt
from ..product_run.states import RESERVED_STATES
from ..product_run.turn_stamp import STAMP_BOUND, STAMP_UNSCOPED, read_product_run_stamp
from .turn_execution_snapshot import closed_value

RUN_IDENTITY_KINDS = ("product_run", "unscoped_turn", "compat_turn", "unresolved")

# Reserved states are outside the readable set on purpose (never a success claim).
_READABLE_STATES = frozenset(RUN_STATES) - RESERVED_STATES
_END_REASONS = frozenset(RUN_END_REASONS)


@dataclass(frozen=True, slots=True)
class ResolvedTurnRun:
    """The stamped run/attempt as stored, loaded for the session owner only."""

    run_id: str
    run_state: Any
    attempt_id: str
    attempt_number: int
    attempt_state: Any
    attempt_end_reason: Any


async def resolve_stamped_turn_run(
    db: AsyncSession,
    *,
    context_snapshot: Any,
    session_id: str,
    owner_user_id: str,
) -> ResolvedTurnRun | None:
    """Load the run/attempt named by a bound stamp, or ``None`` when it does not resolve.

    Every scope condition is part of the one query, so a mismatch is
    indistinguishable from an absent row.
    """
    stamp = read_product_run_stamp(context_snapshot)
    if stamp.status != STAMP_BOUND:
        return None
    rows = (
        await db.execute(
            select(
                ProductRun.id,
                ProductRun.state,
                ProductRunAttempt.id,
                ProductRunAttempt.attempt_number,
                ProductRunAttempt.state,
                ProductRunAttempt.end_reason,
            )
            .join(ProductRunAttempt, ProductRunAttempt.run_id == ProductRun.id)
            .join(ChatSession, ChatSession.id == ProductRun.session_id)
            .where(
                ProductRun.id == stamp.run_id,
                ProductRunAttempt.id == stamp.attempt_id,
                ProductRunAttempt.attempt_number == stamp.attempt_number,
                ProductRun.origin == stamp.origin,
                ProductRun.session_id == session_id,
                ProductRun.owner_user_id == owner_user_id,
                ChatSession.user_id == owner_user_id,
                ChatSession.project_id == ProductRun.workspace_id,
                ProductRunAttempt.workspace_id == ProductRun.workspace_id,
            )
            .limit(2)
        )
    ).all()
    if len(rows) != 1:
        return None
    run_id, run_state, attempt_id, attempt_number, attempt_state, end_reason = rows[0]
    return ResolvedTurnRun(run_id, run_state, attempt_id, attempt_number, attempt_state, end_reason)


def _identity(kind: str) -> dict[str, Any]:
    return {"kind": kind, "product_run_id": None, "run_state": None, "attempt": None}


def build_run_identity(context_snapshot: Any, resolved: ResolvedTurnRun | None) -> dict[str, Any]:
    """Closed ``run_identity`` section; ``resolved`` must come from :func:`resolve_stamped_turn_run`."""
    stamp = read_product_run_stamp(context_snapshot)
    if stamp.status == "missing":
        return _identity("compat_turn")
    if stamp.status == STAMP_UNSCOPED:
        return _identity("unscoped_turn")
    if (
        stamp.status != STAMP_BOUND
        or resolved is None
        or (resolved.run_id, resolved.attempt_id, resolved.attempt_number)
        != (stamp.run_id, stamp.attempt_id, stamp.attempt_number)
    ):
        return _identity("unresolved")
    end_reason = closed_value(resolved.attempt_end_reason, _END_REASONS)
    return {
        "kind": "product_run",
        "product_run_id": stamp.run_id,
        "run_state": closed_value(resolved.run_state, _READABLE_STATES),
        "attempt": {
            "id": stamp.attempt_id,
            "number": stamp.attempt_number,
            "state": closed_value(resolved.attempt_state, _READABLE_STATES),
            "end_reason": None if resolved.attempt_end_reason is None else end_reason,
        },
    }


__all__ = [
    "RUN_IDENTITY_KINDS",
    "ResolvedTurnRun",
    "build_run_identity",
    "resolve_stamped_turn_run",
]
