"""Agent-run usage block for governed coding delivery comments. Appended server-side at the ticket-tool boundary, so the
model can neither omit nor fabricate it."""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session as ChatSession
from ....models import UsageEvent

logger = logging.getLogger(__name__)

USAGE_BLOCK_HEADER = "Octryx agent run metrics"


async def build_agent_usage_block(db: AsyncSession, session_id: str) -> str:
    events = (
        (
            await db.execute(
                select(UsageEvent)
                .where(UsageEvent.session_id == session_id)
                .order_by(UsageEvent.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    if not events:
        return ""
    tokens_in = sum(int(event.tokens_in or 0) for event in events)
    tokens_out = sum(int(event.tokens_out or 0) for event in events)
    cost = sum((Decimal(str(event.cost)) for event in events if event.cost is not None), Decimal("0"))
    models = sorted({f"{event.provider or 'unknown'}/{event.model or 'unknown'}" for event in events})
    started = events[0].created_at
    ended = events[-1].created_at
    window = "-"
    if started and ended:
        window = f"{started:%Y-%m-%d %H:%M} - {ended:%H:%M} UTC" if started.date() == ended.date() else (
            f"{started:%Y-%m-%d %H:%M} - {ended:%Y-%m-%d %H:%M} UTC"
        )
    cost_line = f"{cost:.4f}" if cost > 0 else "not priced (no pricing configured for the model)"
    return "\n".join(
        [
            "----",
            f"{USAGE_BLOCK_HEADER} (as of delivery):",
            f"* Models: {', '.join(models)}",
            f"* LLM requests: {len(events)}",
            f"* Tokens: {tokens_in:,} in / {tokens_out:,} out",
            f"* Cost: {cost_line}",
            f"* Active window: {window}",
        ]
    )


async def append_agent_usage_block_for_governed_session(
    db: AsyncSession | None,
    session_id: str | None,
    body: str,
) -> str:
    # Idempotent across delivery retries; failures never block the delivery comment itself.
    if db is None or not session_id or USAGE_BLOCK_HEADER in body:
        return body
    try:
        session = await db.get(ChatSession, session_id)
        metadata = dict(getattr(session, "metadata_", None) or {}) if session else {}
        if not isinstance(metadata.get("secure_work_execution"), dict):
            return body
        block = await build_agent_usage_block(db, session_id)
    except Exception:
        logger.exception("agent_usage_block_failed session_id=%s", session_id)
        return body
    if not block:
        return body
    return f"{body.rstrip()}\n\n{block}"


__all__ = [
    "USAGE_BLOCK_HEADER",
    "append_agent_usage_block_for_governed_session",
    "build_agent_usage_block",
]
