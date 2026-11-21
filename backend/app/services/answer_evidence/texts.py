"""The answer evidence guard's texts: prompt catalog keys ``evidence_guard.*``.

The texts are catalog data (seeds in ``services/prompt_catalog/seeds/evidence_guard.py``),
rendered through the turn's prompt set. Keys:

- ``evidence_guard.reminder``: the one system reminder after an uncited answer (model-facing).
- ``evidence_guard.reminder.uncited``: the uncited count line of the reminder.
- ``evidence_guard.reminder.invented``: the invented-link line of the reminder.
- ``evidence_guard.refusal``: the explicit refusal shown instead of the answer (user-facing).
- ``evidence_guard.refusal.uncited``: the uncited part of the refusal reason.
- ``evidence_guard.refusal.invented``: the invented-link part of the refusal reason.
- ``evidence_guard.refusal.sources``: the heading of the source list in the refusal.

``REMINDER_MARKER`` is a protocol marker, not configurable text: the turn counts its reminder by
it, so it stays in code and is prepended to the rendered reminder.
"""

from __future__ import annotations

from ..prompt_catalog import render_prompt

# The reminder carries this tag so the turn can count it in its own messages (one reminder only).
REMINDER_MARKER = "[answer_evidence_reminder]"
REMINDER_KEY = "evidence_guard.reminder"


def guard_text(key: str, **values: object) -> str:
    text = render_prompt(key, **values)
    return f"{REMINDER_MARKER} {text}" if key == REMINDER_KEY else text


__all__ = ["REMINDER_KEY", "REMINDER_MARKER", "guard_text"]
