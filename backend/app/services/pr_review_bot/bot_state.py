"""What the review bot remembers per repository between polls (stage D), in ``config_json["pr_review_bot_state"]``.

- ``comment_cursor``: the time of the last comment poll (ISO 8601); the next poll reads from a little before it;
- ``handled``: the ids of the last comments that carried a command (a comment is acted on once, from a webhook or a
  poll);
- ``paused``: the pull requests whose reviews ``@octryx pause`` stopped.

The repository form never sends this key, so saving the repository keeps it (``code_intelligence.repository``).
"""

from __future__ import annotations

from typing import Any

from ...models.runtime.code_intelligence import CodeRepository

STATE_KEY = "pr_review_bot_state"
MAX_HANDLED = 500


def state_of(record: CodeRepository | None) -> dict[str, Any]:
    return dict(dict(record.config_json or {}).get(STATE_KEY) or {}) if record is not None else {}


def _store(record: CodeRepository, **values: Any) -> None:
    record.config_json = {**dict(record.config_json or {}), STATE_KEY: {**state_of(record), **values}}


def is_paused(record: CodeRepository | None, pr_id: str) -> bool:
    return str(pr_id) in [str(item) for item in state_of(record).get("paused") or []]


def set_paused(record: CodeRepository, pr_id: str, paused: bool) -> None:
    current = [str(item) for item in state_of(record).get("paused") or [] if str(item) != str(pr_id)]
    _store(record, paused=[*current, str(pr_id)] if paused else current)


def first_time(record: CodeRepository, comment_id: str) -> bool:
    """Whether the comment is acted on for the first time; it is remembered either way."""
    handled = [str(item) for item in state_of(record).get("handled") or []]
    if str(comment_id) in handled:
        return False
    _store(record, handled=[*handled, str(comment_id)][-MAX_HANDLED:])
    return True


def cursor(record: CodeRepository) -> str:
    return str(state_of(record).get("comment_cursor") or "")


def set_cursor(record: CodeRepository, moment: str) -> None:
    _store(record, comment_cursor=moment)


__all__ = ["STATE_KEY", "cursor", "first_time", "is_paused", "set_cursor", "set_paused", "state_of"]
