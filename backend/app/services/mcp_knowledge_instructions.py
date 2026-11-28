"""The Knowledge MCP server instructions: the catalog seed at startup, the request's Workspace text per connection."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.prompt_catalog.seeds.knowledge import SPECS as KNOWLEDGE_SEEDS

from .prompt_catalog import resolve_prompt_set
from .prompt_catalog.mcp_descriptions import bind_connection_instructions
from .work_role_model.grant_checks import NO_ROLE_EN, empty_reason
from .work_role_model.surfaces import mcp_grant

INSTRUCTIONS_KEY = "knowledge.mcp.instructions"


def _instructions_seed() -> str:
    return next(spec.seed for spec in KNOWLEDGE_SEEDS if spec.key == "knowledge.mcp.instructions")


async def serve_connection_instructions(db: AsyncSession, bound_project_ids: Any, *, user_id: str | None = None
                                        ) -> None:
    bound = [str(item) for item in (bound_project_ids or []) if item]
    workspace_id = bound[0] if len(bound) == 1 else None
    prompt_set = await resolve_prompt_set(db, workspace_id=workspace_id)
    instructions = prompt_set.render(INSTRUCTIONS_KEY)
    grant = await mcp_grant(db, user_id, workspace_id)
    if grant is not None and empty_reason(grant):
        instructions = f"{NO_ROLE_EN}\n\n{instructions}"
    bind_connection_instructions(instructions)
