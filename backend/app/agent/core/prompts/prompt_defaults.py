"""Thinking-mode selection for prompt assembly; the instruction texts are catalog keys."""

from __future__ import annotations

from ....services.prompt_catalog import render_prompt

#: Thinking levels with their own instruction key; any other level uses ``system.thinking.default``.
_LEVEL_KEYS = {"light": "system.thinking.light", "deep": "system.thinking.deep"}


def resolve_prompt_thinking_mode(
    thinking_level: str | None,
    *,
    prompt_variant: str,
) -> tuple[str, str] | None:
    if not thinking_level:
        return None
    if thinking_level == "off":
        if prompt_variant == "minimal":
            return "off", render_prompt("system.thinking.minimal_off")
        if prompt_variant in {"summary", "admin"}:
            return None
        return "off", render_prompt("system.thinking.off")
    if prompt_variant == "minimal":
        return thinking_level, render_prompt("system.thinking.minimal")
    if prompt_variant == "summary":
        return "light", render_prompt("system.thinking.summary")
    if prompt_variant == "admin":
        return "light", render_prompt("system.thinking.admin")
    return thinking_level, render_prompt(_LEVEL_KEYS.get(thinking_level, "system.thinking.default"))
