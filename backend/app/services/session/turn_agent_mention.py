"""Exact-name ``@mention`` resolution of an owned Agent Definition.

A mention is an explicit user choice only when it names a configured agent exactly:
``@`` at the start of the prompt or after whitespace or an opening bracket/quote, then
the agent's configured name (compared case-insensitively), then the end of the prompt or
a character that cannot continue a name. ``@Backend`` therefore never selects
"Backend Engineer Agent", and ``@Backendish`` never selects "Backend". When two
configured names both match at one mention (``Backend`` and ``Backend Engineer Agent``
for ``@Backend Engineer Agent``), the longer, fully named one is the mention.

A prompt whose mentions name different agents, or a name several owned agents share, is
``agent_mention_ambiguous``: it is never resolved by picking one.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentDefinition
from ..agent_visibility import visible_agent_clause, workspace_agent_clause
from .turn_refusals import TurnRefusalState, TurnRefusedError

MENTION_AMBIGUOUS_DETAIL = "The prompt mentions more than one agent, or a name several agents share"
_MENTION_OPENERS = frozenset("([{\"'")


@dataclass(frozen=True, slots=True)
class NamedAgent:
    agent_id: str
    name: str


def _continues_name(character: str) -> bool:
    return character.isalnum() or character in "_-"


def _starts_mention(prompt: str, position: int) -> bool:
    if position == 0:
        return True
    previous = prompt[position - 1]
    return previous.isspace() or previous in _MENTION_OPENERS


def _names_exactly(text: str, name: str) -> bool:
    if len(text) < len(name) or text[: len(name)].casefold() != name.casefold():
        return False
    return len(text) == len(name) or not _continues_name(text[len(name)])


def mentioned_agent_id(prompt: str, agents: Iterable[NamedAgent]) -> str:
    """The one agent the prompt mentions by exact name; ``""`` when it mentions none."""
    named = [agent for agent in agents if agent.name.strip() == agent.name and agent.name]
    mentioned: set[str] = set()
    for position, character in enumerate(prompt):
        if character != "@" or not _starts_mention(prompt, position):
            continue
        rest = prompt[position + 1 :]
        matches = [agent for agent in named if _names_exactly(rest, agent.name)]
        if not matches:
            continue
        longest = max(len(agent.name) for agent in matches)
        mentioned.update(agent.agent_id for agent in matches if len(agent.name) == longest)
    if len(mentioned) > 1:
        raise TurnRefusedError(TurnRefusalState.AGENT_MENTION_AMBIGUOUS, MENTION_AMBIGUOUS_DETAIL)
    return next(iter(mentioned), "")


async def resolve_mentioned_agent_id(
    db: AsyncSession, *, owner_id: str, prompt: str, project_id: str | None = None
) -> str:
    """The visible agent (own, Workspace-shared, global, built-in) the prompt mentions by exact name, if any.

    In a Workspace turn only global, built-in and that Workspace's agents are candidates.
    """
    if "@" not in prompt:
        return ""
    query = select(AgentDefinition.id, AgentDefinition.name).where(await visible_agent_clause(db, owner_id))
    if project_id:
        query = query.where(workspace_agent_clause(project_id))
    rows = (await db.execute(query)).all()
    return mentioned_agent_id(prompt, (NamedAgent(agent_id=row.id, name=str(row.name or "").strip()) for row in rows))


__all__ = ["MENTION_AMBIGUOUS_DETAIL", "NamedAgent", "mentioned_agent_id", "resolve_mentioned_agent_id"]
