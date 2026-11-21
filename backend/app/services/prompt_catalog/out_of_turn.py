"""Prompt sets for code that renders catalog prompts outside an agent turn.

Background jobs (episode and memory capture, graph extraction, evaluation, judges, the
README worker, Teams calls, sub-agent group resumes, coordinator controls, approval resumes,
governed coding starts) run without a turn's bound prompt set. They use the bound set
when one is bound (the code runs inside a turn) and otherwise resolve the Workspace's own
set explicitly: Workspace > global > seed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from .prompt_set import PromptSet, bound_prompt_set, prompt_set_scope
from .resolver import resolve_prompt_set


async def prompt_set_for(db: AsyncSession, *, workspace_id: str | None) -> PromptSet:
    """The bound turn set, else the set resolved for this Workspace (global when ``None``)."""
    bound = bound_prompt_set()
    if bound is not None:
        return bound
    return await resolve_prompt_set(db, workspace_id=workspace_id or None)


async def render_prompt_for_scope(
    db: AsyncSession, key: str, /, *, workspace_id: str | None, **variables: object
) -> str:
    """Render one key outside a turn, at the scope of the Workspace it is for."""
    return (await prompt_set_for(db, workspace_id=workspace_id)).render(key, **variables)


@asynccontextmanager
async def scoped_prompt_set(db: AsyncSession, *, workspace_id: str | None) -> AsyncIterator[PromptSet]:
    """Bind :func:`prompt_set_for` for a block so ``render_prompt`` works inside it."""
    prompt_set = await prompt_set_for(db, workspace_id=workspace_id)
    with prompt_set_scope(prompt_set):
        yield prompt_set


def single_workspace(project_ids: Iterable[str] | str | None) -> str | None:
    """The one Workspace of a retrieval scope, or ``None`` (global prompts) for zero or several."""
    if isinstance(project_ids, str):
        return project_ids or None
    ids = [item for item in (project_ids or []) if item]
    return ids[0] if len(ids) == 1 else None


__all__ = ["prompt_set_for", "render_prompt_for_scope", "scoped_prompt_set", "single_workspace"]
