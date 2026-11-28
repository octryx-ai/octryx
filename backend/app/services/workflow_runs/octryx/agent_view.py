"""The platform agent an octryx-claude session works as."""

from __future__ import annotations

from collections.abc import Iterable
from hashlib import sha256
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...platform_agents.catalog import ASSISTANT
from ..graph import NODE_PHASE, PhasedNode
from ..phase_agents import agent_refusal, phase_agent_key, phase_class, platform_agent

REASON_AGENT_RUNTIME_UNAVAILABLE = "agent_runtime_unavailable"
REASON_AGENT_RUNTIME_UNVERIFIED = "agent_runtime_unverified"


async def agent_view_or_refusal(db: AsyncSession, key: str, *, needed_class: str = "read_only"
                                ) -> tuple[dict[str, Any] | None, str]:
    agent = await platform_agent(db, key)
    reason = agent_refusal(agent, needed_class=needed_class)
    if reason:
        return None, reason
    return {"key": key, "name": agent.name, "version": agent.revision_number, "revision_id": agent.revision_id,
            "checksum": agent.checksum, "instructions": agent.instructions,
            "digest": "sha256:" + sha256(agent.instructions.encode("utf-8")).hexdigest(),
            "tools_deny": list(agent.tools_deny)}, ""


async def agent_view(db: AsyncSession, key: str, *, needed_class: str = "read_only") -> dict[str, Any] | None:
    return (await agent_view_or_refusal(db, key, needed_class=needed_class))[0]


def agent_refusal_state(key: str, reason: str) -> dict[str, str]:
    return {"state": "needs_configuration", "reason": reason, "agent": key}


async def phase_agent_view(db: AsyncSession, node: PhasedNode | None) -> tuple[dict[str, Any] | None, str]:
    key = phase_agent_key(node.config) if node is not None and node.kind == NODE_PHASE else ""
    if not key:
        return None, ""
    return await agent_view_or_refusal(db, key, needed_class=phase_class(node.config))


async def outside_run_agent(db: AsyncSession) -> dict[str, Any]:
    view, reason = await agent_view_or_refusal(db, ASSISTANT)
    if view is None:
        return {**agent_refusal_state(ASSISTANT, reason), "capability_class": "read_only"}
    return {**view, "capability_class": "read_only"}


async def phase_agent_model_refusal(db: AsyncSession, session_id: str, served: Iterable[str],
                                    labels: Iterable[str] = ()) -> str | None:
    from ..graph import graph_for_run
    from ..records import active_run_for_session

    run = await active_run_for_session(db, session_id)
    if run is None or run.status != "running":
        return None
    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id or "")
    key = phase_agent_key(node.config) if node is not None and node.kind == NODE_PHASE else ""
    if not key:
        return None
    agent = await platform_agent(db, key)
    reason = agent_refusal(agent, needed_class=phase_class(node.config))
    if reason:
        return reason
    return None
