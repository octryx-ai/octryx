"""Pure text heuristics used by assistant response guards.

The phrase tables live in ``app.services.response_guard_policy``; this module
uses only ``REPETITIVE_TRANSITION_MARKERS`` from it. Here is the guard text
logic: whitespace normalization, collapsing of near-identical consecutive
clauses, repeated-transition detection, response signatures, the
step-completion check, and similarity scoring.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from ....services.response_guard_policy import REPETITIVE_TRANSITION_MARKERS


def normalize_response_text(content: str) -> str:
    return re.sub(r"\s+", " ", (content or "").strip())


def collapse_repeated_clauses(content: str) -> str:
    text = normalize_response_text(content)
    if not text:
        return ""
    clauses = [clause.strip() for clause in re.split(r"(?<=[\.:;!?])\s+", text) if clause.strip()]
    if not clauses:
        return text
    collapsed: list[str] = []
    for clause in clauses:
        if not collapsed:
            collapsed.append(clause)
            continue
        previous = collapsed[-1]
        if SequenceMatcher(None, previous[:220].lower(), clause[:220].lower()).ratio() >= 0.96:
            continue
        collapsed.append(clause)
    return " ".join(collapsed)


def looks_like_repetitive_transition(content: str) -> bool:
    # Similar immutable references contain words such as repository_id; they
    # are evidence locators, not repeated announcements. This changes only the
    # repetition heuristic; the original answer still reaches citation checks.
    narrative = re.sub(r"\[[^\]\n]*\]\((?:https?://|/chat\?)[^\s)]*\)", "", content or "")
    text = collapse_repeated_clauses(narrative)
    if not text:
        return False
    clauses = [
        clause.strip().lower()
        for clause in re.split(r"(?<=[\.:;!?])\s+", normalize_response_text(narrative))
        if clause.strip()
    ]
    for index in range(1, len(clauses)):
        if SequenceMatcher(None, clauses[index - 1][:220], clauses[index][:220]).ratio() >= 0.96:
            # Two near-identical consecutive clauses only count when they carry a transition marker.
            if any(marker in clauses[index] for marker in REPETITIVE_TRANSITION_MARKERS):
                return True
    return False


def assistant_no_tool_response_signature(content: str) -> str | None:
    text = collapse_repeated_clauses(content).lower()
    if len(text) < 32:
        return None
    text = re.sub(r"`[^`]+`", "`item`", text)
    text = re.sub(r"\d+", "<n>", text)
    return text[:240]


def looks_like_step_completion_summary(content: str) -> bool:
    text = (content or "").strip().lower()
    if not text:
        return False
    return (
        ("step" in text and "complete" in text)
        or ("inventory" in text and "complete" in text)
        or ("classification" in text and "complete" in text)
    )


def assistant_no_tool_response_similarity(previous: str, current: str) -> float:
    left = collapse_repeated_clauses(previous).lower()
    right = collapse_repeated_clauses(current).lower()
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left[:600], right[:600]).ratio()
