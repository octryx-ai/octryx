"""The texts a workflow run sends its agent, from the prompt catalog (``prompt_catalog/seeds/run.py``), out of the
code."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from ..prompt_catalog.prompt_set import PromptSet, bound_prompt_set, prompt_set_scope
from ..prompt_catalog.resolver import resolve_prompt_set, seed_prompt_set

PREFIX = "run."


async def run_prompt_set(db: Any, run: Any) -> PromptSet:
    return await resolve_prompt_set(db, workspace_id=getattr(run, "project_id", None),
                                    workflow_key=getattr(run, "workflow_key", None))


@asynccontextmanager
async def run_texts(db: Any, run: Any) -> AsyncIterator[PromptSet]:
    prompt_set = await run_prompt_set(db, run)
    with prompt_set_scope(prompt_set):
        yield prompt_set


LAUNCHER_PREFIX = f"{PREFIX}launcher."


async def launcher_texts(db: Any, run: Any) -> dict[str, str]:
    prompt_set = await run_prompt_set(db, run)
    return {key: prompt_set.resolved(key).body for key in prompt_set.prompts if key.startswith(LAUNCHER_PREFIX)}


def run_text(name: str, /, **variables: object) -> str:
    return (bound_prompt_set() or seed_prompt_set()).render(f"{PREFIX}{name}", **variables)


__all__ = ["LAUNCHER_PREFIX", "PREFIX", "launcher_texts", "run_prompt_set", "run_text", "run_texts"]
