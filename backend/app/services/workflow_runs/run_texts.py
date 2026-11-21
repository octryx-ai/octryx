"""The texts a workflow run sends its agent, from the prompt catalog (``prompt_catalog/seeds/run.py``), out of
the code. The builders only compute the placeholders.

- :func:`run_texts` resolves the run's set (global, the run's workflow ``workflow:<key>``, its Workspace) and binds
  it for a block; the entry points that start a turn wrap their prompt building in it;
- :func:`run_text` renders ``run.<name>`` from the bound set, else from the seeds (a builder called outside such a
  block, a test).
"""

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
    """Bind the run's prompt set while the block builds its prompts."""
    prompt_set = await run_prompt_set(db, run)
    with prompt_set_scope(prompt_set):
        yield prompt_set


LAUNCHER_PREFIX = f"{PREFIX}launcher."


async def launcher_texts(db: Any, run: Any) -> dict[str, str]:
    """The launcher's texts of this run (``run.launcher.*``, the resolved bodies with their placeholders): the run
    contract's ``prompt_texts``; the launcher fills them."""
    prompt_set = await run_prompt_set(db, run)
    return {key: prompt_set.resolved(key).body for key in prompt_set.prompts if key.startswith(LAUNCHER_PREFIX)}


def run_text(name: str, /, **variables: object) -> str:
    """``run.<name>`` rendered with ``variables`` (every placeholder of the key)."""
    return (bound_prompt_set() or seed_prompt_set()).render(f"{PREFIX}{name}", **variables)


__all__ = ["LAUNCHER_PREFIX", "PREFIX", "launcher_texts", "run_prompt_set", "run_text", "run_texts"]
