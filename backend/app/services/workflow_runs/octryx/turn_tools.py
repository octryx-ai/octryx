"""What a device turn of a run starts with: its built-in tools and its system prompt, both as data.

Measured on a small bug run: of 557k input tokens, ~324k (~18k per call) were the system prompt and
the tool definitions. Measured with ``claude -p`` probes: Claude Code's Agent tool alone adds ~2.3k tokens to every
call; a small bug's phase never starts a sub-agent. So the built-in tools a phase turn gets are data:
``"builtin_tools": [...]`` on the phase's config, else on the run's size class; without either the launcher uses its
lean tool set. The list is the same for every turn of that class and phase, sorted as written, so the prompt cache
keeps its prefix. The device's system prompt comes from the prompt catalog (``run.device.system_prompt``), which a
workflow or a Workspace may override like every other run text.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun

KEY = "builtin_tools"


def builtin_tools(run: WorkflowRun | None, phase: Any) -> list[str] | None:
    """The phase's own list, else its size class's; ``None`` leaves the launcher's default."""
    from ..size_class import class_config

    for source in (dict(getattr(phase, "config", None) or {}), class_config(run)):
        value = source.get(KEY)
        if isinstance(value, list) and value and all(isinstance(name, str) and name for name in value):
            return list(dict.fromkeys(value))
    return None


async def device_system_prompt(db: AsyncSession, run: WorkflowRun | None) -> str:
    """The run turn's system prompt with the run's own catalog versions; ``""`` without a run."""
    if run is None:
        return ""
    from ..run_texts import run_text, run_texts

    async with run_texts(db, run):
        return run_text("device.system_prompt")


async def device_session_prompts(db: AsyncSession, run: WorkflowRun | None) -> dict[str, str]:
    """The run paragraphs of a story session and of a plain one (``run.device.*_session_prompt``), with the run's own
    catalog versions; ``{}`` without a run (a turn without a run is no story session)."""
    if run is None:
        return {}
    from ..run_texts import run_text, run_texts

    async with run_texts(db, run):
        return {"story_prompt": run_text("device.story_session_prompt"),
                "plain_prompt": run_text("device.plain_session_prompt")}


__all__ = ["KEY", "builtin_tools", "device_session_prompts", "device_system_prompt"]
