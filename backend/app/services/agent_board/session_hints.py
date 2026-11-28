"""The board hints of one gateway session's hook answer."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentPresence
from .automation import available_for_session, handoff_nudges, handoff_offers, refresh_offers


async def session_handoff_hints(
    db: AsyncSession, *, session_key: str, agent_hash: str, project_id: str
) -> dict[str, Any]:
    presence = (
        await db.execute(select(AgentPresence).where(AgentPresence.session_key == session_key))
    ).scalar_one_or_none()
    from .auto_takeover import workspace_handoff_policy

    await refresh_offers(db, project_id, await workspace_handoff_policy(db, project_id))
    available = (await available_for_session(db, presence, agent_hash) if presence is not None
                 else {"count": 0, "items": []})
    offers = await handoff_offers(db, agent_hash, project_id)
    return {
        "available_handoffs": available,
        "handoff_offers": [offer["work_item_key"] for offer in offers],
        "handoff_nudges": await handoff_nudges(db, agent_hash, project_id) + offers,
    }


__all__ = ["session_handoff_hints"]
