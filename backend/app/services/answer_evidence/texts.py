"""The answer evidence guard's texts: prompt catalog keys ``evidence_guard.*``."""

from __future__ import annotations

from ..prompt_catalog import render_prompt

# The reminder carries this tag so the turn can count it in its own messages (one reminder only).
REMINDER_MARKER = "[answer_evidence_reminder]"
REMINDER_KEY = "evidence_guard.reminder"


def guard_text(key: str, **values: object) -> str:
    text = render_prompt(key, **values)
    return f"{REMINDER_MARKER} {text}" if key == REMINDER_KEY else text


__all__ = ["REMINDER_KEY", "REMINDER_MARKER", "guard_text"]
