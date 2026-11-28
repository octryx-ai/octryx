"""What a device turn of a run starts with: its built-in tools and its system prompt, both as data."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun

KEY = "builtin_tools"


def builtin_tools(run: WorkflowRun | None, phase: Any) -> list[str] | None:
    from ..size_class import class_config

    for source in (dict(getattr(phase, "config", None) or {}), class_config(run)):
        value = source.get(KEY)
        if isinstance(value, list) and value and all(isinstance(name, str) and name for name in value):
            return list(dict.fromkeys(value))
    return None


async def device_system_prompt(db: AsyncSession, run: WorkflowRun | None) -> str:
    if run is None:
        return ""
    from ..run_texts import run_text, run_texts

    async with run_texts(db, run):
        return run_text("device.system_prompt")


async def device_session_prompts(db: AsyncSession, run: WorkflowRun | None) -> dict[str, str]:
    if run is None:
        return {}
    from ..run_texts import run_text, run_texts

    async with run_texts(db, run):
        return {"story_prompt": run_text("device.story_session_prompt"),
                "plain_prompt": run_text("device.plain_session_prompt")}


__all__ = ["KEY", "builtin_tools", "device_session_prompts", "device_system_prompt"]
