"""Assistant response and step-guard helpers for the agent engine."""

from __future__ import annotations

import re
from typing import Any

from ....services.prompt_catalog import render_prompt
from ....services.response_guard_policy import (
    ACKNOWLEDGEMENT_REPLY_PHRASES,
    OFFER_SENTENCE_PATTERN,
    PLACEHOLDER_REPLY_PHRASES,
    SHORT_REPLY_REQUEST_PATTERN,
    TRANSITIONAL_ACTION_MARKERS,
    TRANSITIONAL_ASSISTANT_PATTERN,
    TRANSITIONAL_CONFIRMATION_PATTERN,
    TRANSITIONAL_RESPONSE_HINT_TERMS,
    TRANSITIONAL_SEGUE_PATTERN,
    TRANSITIONAL_SUBJECT_MARKERS,
)
from ._response_guard_text import (
    assistant_no_tool_response_signature as _assistant_no_tool_response_signature,
)
from ._response_guard_text import (
    assistant_no_tool_response_similarity as _assistant_no_tool_response_similarity,
)
from ._response_guard_text import (
    collapse_repeated_clauses as _collapse_repeated_clauses,
)
from ._response_guard_text import (
    looks_like_repetitive_transition as _looks_like_repetitive_transition,
)
from ._response_guard_text import (
    looks_like_step_completion_summary as _looks_like_step_completion_summary,
)
from .stop_text import agent_stop_text

_TEXTUAL_TOOL_REQUEST_PATTERN = re.compile(r"^\s*Tool request\s+[A-Za-z_][\w.-]*\s*:", re.IGNORECASE)
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?;])\s+|\n+")


def _without_offer_sentences(text: str) -> str:
    """Drop sentences that offer next steps to the user; keep everything else.

    "If you want to continue, tell me …" or "For example, I can search Jira …"
    after a finished answer hands the turn back to the user; it is not an
    announcement of an action the assistant takes now.
    """
    sentences = [sentence.strip() for sentence in _SENTENCE_SPLIT_PATTERN.split(text or "") if sentence.strip()]
    return " ".join(sentence for sentence in sentences if not OFFER_SENTENCE_PATTERN.search(sentence))


def get_step_field(step: dict[str, Any] | None, camel_key: str, snake_key: str, default: Any = None) -> Any:
    if not step:
        return default
    value = step.get(camel_key)
    if value is not None:
        return value
    value = step.get(snake_key)
    if value is not None:
        return value
    return default


def get_step_allowed_tools(step: dict[str, Any] | None) -> list[str]:
    raw_tools = get_step_field(step, "allowedTools", "allowed_tools", []) or []
    return list(dict.fromkeys(str(tool_name).strip() for tool_name in raw_tools if str(tool_name).strip()))


def is_transitional_assistant_response(content: str, tool_calls: list[Any] | None, tools_available: bool) -> bool:
    if tool_calls or not tools_available:
        return False
    text = _collapse_repeated_clauses(content)
    if not text:
        return False
    if _looks_like_repetitive_transition(content):
        return True
    if TRANSITIONAL_CONFIRMATION_PATTERN.search(text):
        return True
    # Offers of next steps are judged as the end of an answer, not as an announcement.
    announcement = _without_offer_sentences(text)
    if not announcement:
        return False
    lowered = announcement.lower()
    if len(text) > 400 and not TRANSITIONAL_SEGUE_PATTERN.search(announcement):
        return False
    if not TRANSITIONAL_ASSISTANT_PATTERN.search(announcement):
        if not TRANSITIONAL_SEGUE_PATTERN.search(announcement):
            return False
    return any(term in lowered for term in TRANSITIONAL_RESPONSE_HINT_TERMS)


def is_transitional_tool_call_preamble(content: str, tool_calls: list[Any] | None) -> bool:
    if not tool_calls:
        return False
    text = (content or "").strip()
    if not text:
        return False
    if looks_like_step_completion_summary(text):
        return True
    if len(text) > 320:
        return False
    lowered = text.lower()
    return (
        any(marker in lowered for marker in TRANSITIONAL_ACTION_MARKERS)
        and any(marker in lowered for marker in TRANSITIONAL_SUBJECT_MARKERS)
    ) or TRANSITIONAL_ASSISTANT_PATTERN.search(text) is not None


def is_non_substantive_assistant_response(
    content: str,
    tool_calls: list[Any] | None,
    user_message: str | None = None,
) -> bool:
    """True when the reply is a placeholder, judged by content, not length.

    A short real answer ("42", "Yes", "Bern") is substantive. A bare
    acknowledgement ("OK", "Sure") is a placeholder unless the user asked for
    exactly such a short reply ("Reply only with the word OK.").
    """
    if tool_calls:
        return False
    text = (content or "").strip()
    if not text:
        return True
    lowered = text.lower()
    if _TEXTUAL_TOOL_REQUEST_PATTERN.search(text):
        return True
    if "<tool_call>" in lowered or "<function=" in lowered or "<function>" in lowered:
        return True
    if text in {"⏳", "...", "…", "-", "—"}:
        return True
    normalized = re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)
    if not normalized:
        return True
    phrase = " ".join(re.sub(r"[^\w\s]+", "", lowered, flags=re.UNICODE).split())
    if phrase in PLACEHOLDER_REPLY_PHRASES:
        return True
    if phrase in ACKNOWLEDGEMENT_REPLY_PHRASES:
        return not SHORT_REPLY_REQUEST_PATTERN.search(str(user_message or ""))
    return False


def strip_textual_tool_request_preamble(content: str) -> str:
    lines = str(content or "").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if not _TEXTUAL_TOOL_REQUEST_PATTERN.search(line):
            break
        index += 1
    if index == 0 or index >= len(lines):
        return str(content or "")
    stripped = "\n".join(lines[index:]).strip()
    return stripped or str(content or "")


def allows_noop_step_completion(step: dict[str, Any] | None, content: str) -> bool:
    if not step:
        return False
    text = (content or "").strip().lower()
    if not text:
        return False
    step_text = " ".join(
        str(get_step_field(step, key, key.replace("Criteria", "_criteria").replace("Type", "_type"), "") or "")
        .strip()
        .lower()
        for key in ("instructions", "successCriteria", "name")
    )
    if not any(marker in step_text for marker in ("no change possible", "clear justification")):
        return False
    return any(
        marker in text
        for marker in (
            "no confluence updates",
            "no confluence changes",
            "no changes made",
            "no update performed",
            "no updates performed",
            "justification",
        )
    )


def assistant_no_tool_response_signature(content: str) -> str | None:
    return _assistant_no_tool_response_signature(content)


def looks_like_step_completion_summary(content: str) -> bool:
    return _looks_like_step_completion_summary(content)


def assistant_no_tool_response_similarity(previous: str, current: str) -> float:
    return _assistant_no_tool_response_similarity(previous, current)


def build_required_tool_reminder(step: dict[str, Any] | None) -> str:
    if not step:
        return render_prompt("guard.step.required_tool_reminder_unnamed")
    step_name = str(step.get("name") or "").strip() or "current step"
    return render_prompt("guard.step.required_tool_reminder", step_name=step_name)


def build_stalled_step_message(step: dict[str, Any] | None) -> str:
    step_name = str((step or {}).get("name") or "").strip() or "current step"
    return agent_stop_text("guard.step.stalled_stop", step_name=step_name)


def resolve_allowed_tools_for_step_tool_call(
    *,
    active_steps: list[dict[str, Any]],
    current_step_index: int,
    current_step_tool_activity: bool,
    current_allowed_tool_names: set[str],
    tool_name: str,
) -> tuple[int, bool, set[str]]:
    effective_allowed_tool_names = set(current_allowed_tool_names)
    next_step_index = current_step_index
    next_step_tool_activity = current_step_tool_activity
    if (
        effective_allowed_tool_names
        and tool_name not in effective_allowed_tool_names
        and current_step_tool_activity
        and current_step_index < len(active_steps) - 1
    ):
        next_step = active_steps[current_step_index + 1]
        next_allowed_tool_names = set(get_step_allowed_tools(next_step))
        if not next_allowed_tool_names or tool_name in next_allowed_tool_names:
            next_step_index = current_step_index + 1
            next_step_tool_activity = False
            effective_allowed_tool_names = next_allowed_tool_names
    return next_step_index, next_step_tool_activity, effective_allowed_tool_names

