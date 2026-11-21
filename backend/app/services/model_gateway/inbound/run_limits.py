"""The run's hard limits on every inbound model route (``workflow_runs/octryx/model_guard``).

One call for the seat route, the governed route and the Codex seat: the request body with its model mapped down to
the run's, or the refusal when the run's budget is used up. A session outside a run passes unchanged.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...agent_gateway.contract import STATE_DENIED
from .refusals import InboundRefusal, refusal


async def run_limited_body(db: AsyncSession, session_id: str, body: dict[str, Any], *,
                           engine: str = "") -> dict[str, Any] | InboundRefusal:
    """``engine`` codex on the Codex routes: only Codex's own models are compared there."""
    from ...workflow_runs.octryx.model_guard import guard_model_call

    guarded = await guard_model_call(db, session_id, body, engine=engine)
    if guarded.refusal:
        return refusal(STATE_DENIED, guarded.refusal, http_status=403, hint=guarded.hint)
    return guarded.body


__all__ = ["run_limited_body"]
