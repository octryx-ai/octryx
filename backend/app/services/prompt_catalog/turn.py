"""Resolve the prompt set of one agent turn from its Workspace."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .prompt_set import PromptSet
from .resolver import resolve_prompt_set


async def resolve_turn_prompt_set(db: AsyncSession, *, project_id: str | None) -> PromptSet:
    return await resolve_prompt_set(db, workspace_id=project_id or None)


__all__ = ["resolve_turn_prompt_set"]
