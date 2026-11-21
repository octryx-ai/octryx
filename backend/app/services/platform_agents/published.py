"""The one resolution of a platform agent for execution: its **published** revision (AFS-1).

A platform agent's behaviour — instructions, name, capability ceiling, runtime preference, tools deny, tool surface —
comes only from its highest published revision, on every path (chat turns, phase turns and their bindings, the
octryx run contract, the reviewer, the gateway's runtime check). An edit of the live row is a draft until a second
admin publishes it (``publish_governance``); it never reaches a run, whatever the global
``agent_definition_execution_mode`` says. The live row supplies only identity and the admission switches
(``is_active``), which is checked separately.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentDefinition
from .catalog import ceiling_covers


@dataclass(frozen=True, slots=True)
class PublishedPlatformAgent:
    key: str
    definition_id: str
    active: bool
    revision_id: str | None = None
    revision_number: int | None = None
    checksum: str | None = None
    name: str = ""
    instructions: str = ""
    capability_ceiling: str = "read_only"
    runtime_preference: str = ""
    tools_deny: tuple[str, ...] = ()
    tool_surface: str = "governed"

    @property
    def published(self) -> bool:
        return self.revision_id is not None


async def published_platform_agent(db: AsyncSession, key: str) -> PublishedPlatformAgent | None:
    from app.services.agent_definition_revision_store import get_published_revision

    if not key:
        return None
    row = (await db.execute(select(AgentDefinition).where(AgentDefinition.builtin_key == key))).scalar_one_or_none()
    if row is None:
        return None
    identity = {"key": key, "definition_id": row.id, "active": bool(row.is_active)}
    revision = await get_published_revision(db, row.id)
    if revision is None:
        return PublishedPlatformAgent(**identity)
    snapshot = dict(revision.snapshot.get("definition") or {})
    return PublishedPlatformAgent(
        **identity, revision_id=revision.id, revision_number=int(revision.revision_number),
        checksum=revision.checksum, name=str(snapshot.get("name") or ""),
        instructions=str(snapshot.get("system_prompt") or ""),
        capability_ceiling=str(snapshot.get("capability_ceiling") or "read_only"),
        runtime_preference=str(snapshot.get("runtime_preference") or ""),
        tools_deny=tuple(str(item) for item in snapshot.get("tools_deny") or [] if str(item)),
        tool_surface=str(snapshot.get("tool_surface") or "governed"))


def published_agent_refusal(agent: PublishedPlatformAgent | None, *, needed_class: str = "read_only") -> str:
    """``""`` when the agent may run a phase of ``needed_class``, else the typed reason."""
    if agent is None:
        return "agent_missing"
    if not agent.active:
        return "agent_inactive"
    if not agent.published:
        return "agent_unpublished"
    if not ceiling_covers(agent.capability_ceiling, needed_class):
        return "agent_ceiling"
    return ""
