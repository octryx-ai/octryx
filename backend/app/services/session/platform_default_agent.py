"""The platform Assistant answers every turn that names no agent.

There is no anonymous "turn without an agent": the turn runs as the Assistant, recorded as
``agent_selection_source = platform_default``. An Assistant that is missing, retired or inactive refuses the turn
explicitly (``agent_definition_refused``) — never a silent run without an agent.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentDefinition
from ..platform_agents.catalog import ASSISTANT, PLATFORM_AGENT_KEYS
from .turn_refusals import TurnRefusalState, TurnRefusedError


async def platform_default_agent_id(db: AsyncSession) -> str:
    row = (await db.execute(
        select(AgentDefinition).where(AgentDefinition.builtin_key == ASSISTANT))).scalar_one_or_none()
    if row is None or not row.is_active:
        reason = "agent_missing" if row is None else "agent_inactive"
        raise TurnRefusedError(TurnRefusalState.AGENT_DEFINITION_REFUSED,
                               f"The platform Assistant cannot run ({reason}); an admin must restore it.")
    return row.id


async def is_platform_agent_id(db: AsyncSession, agent_id: str) -> bool:
    if not agent_id:
        return False
    key = (await db.execute(select(AgentDefinition.builtin_key).where(AgentDefinition.id == agent_id))).scalar()
    return str(key or "") in PLATFORM_AGENT_KEYS

