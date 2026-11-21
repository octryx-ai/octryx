"""Repo-local context prompt helpers for agent run preparation."""

from __future__ import annotations

import asyncio
from typing import Any

from ....services.repo_knowledge import (
    discover_repo_knowledge_files,
    select_relevant_repo_knowledge_files,
)
from ....services.repo_microagent import (
    discover_repo_microagents,
    select_relevant_repo_microagents,
)
from ..prompts.repo_prompts import build_repo_knowledge_prompt, build_repo_microagents_prompt


async def load_repo_context_prompts(
    *,
    workspace_root: str,
    project_config: dict[str, Any],
    capability_type: str,
) -> tuple[str, str]:
    """Repository microagents and knowledge files the repository marks ``always_include``.

    The prompt never triggers an entry.
    """
    discovered_repo_microagents, discovered_repo_knowledge = await asyncio.gather(
        asyncio.to_thread(
            discover_repo_microagents,
            workspace_root=workspace_root,
            project_config=project_config,
        ),
        asyncio.to_thread(
            discover_repo_knowledge_files,
            workspace_root=workspace_root,
            project_config=project_config,
        ),
    )
    selected_repo_microagents, selected_repo_knowledge = await asyncio.gather(
        asyncio.to_thread(
            select_relevant_repo_microagents,
            microagents=discovered_repo_microagents,
            capability_type=capability_type,
        ),
        asyncio.to_thread(
            select_relevant_repo_knowledge_files,
            entries=discovered_repo_knowledge,
        ),
    )
    repo_microagents_prompt = (
        build_repo_microagents_prompt(selected_repo_microagents) if selected_repo_microagents else ""
    )
    repo_knowledge_prompt = build_repo_knowledge_prompt(selected_repo_knowledge) if selected_repo_knowledge else ""
    return repo_microagents_prompt, repo_knowledge_prompt
