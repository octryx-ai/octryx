"""The run's hard limits on every inbound model route (``workflow_runs/octryx/model_guard``)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...agent_gateway.contract import STATE_DENIED
from .refusals import InboundRefusal, refusal


async def run_limited_body(db: AsyncSession, session_id: str, body: dict[str, Any], *,
                           engine: str = "") -> dict[str, Any] | InboundRefusal:
    from ...workflow_runs.octryx.model_guard import guard_model_call

    guarded = await guard_model_call(db, session_id, body, engine=engine)
    if guarded.refusal:
        return refusal(STATE_DENIED, guarded.refusal, http_status=403, hint=guarded.hint)
    return guarded.body


__all__ = ["run_limited_body"]
