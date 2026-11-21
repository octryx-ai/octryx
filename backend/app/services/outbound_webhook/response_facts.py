"""Fixed facts about a webhook receiver's answer; the answer's body is never stored.

A receiver's response body is foreign text: it can echo the delivered payload, carry the
receiver's internal hosts, paths or tokens. A delivery keeps only the HTTP status, the body's
length in bytes and a closed outcome. The ``response_body`` column holds exactly that as one line, ``outcome=accepted
http_status=200 content_length=17``, and serialization returns it only when it matches this grammar, so a
stored raw body is never echoed.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

OUTCOME_ACCEPTED = "accepted"
OUTCOME_REDIRECT_NOT_FOLLOWED = "redirect_not_followed"
OUTCOME_REJECTED = "rejected"
OUTCOME_RECEIVER_ERROR = "receiver_error"
OUTCOME_UNEXPECTED_STATUS = "unexpected_status"

DELIVERY_OUTCOMES = frozenset(
    {
        OUTCOME_ACCEPTED,
        OUTCOME_REDIRECT_NOT_FOLLOWED,
        OUTCOME_REJECTED,
        OUTCOME_RECEIVER_ERROR,
        OUTCOME_UNEXPECTED_STATUS,
    }
)

_FACTS_LINE = re.compile(r"^outcome=([a-z_]{1,32}) http_status=(\d{3}) content_length=(\d{1,12})$")


def delivery_outcome(status_code: int) -> str:
    if 200 <= status_code < 300:
        return OUTCOME_ACCEPTED
    if 300 <= status_code < 400:
        return OUTCOME_REDIRECT_NOT_FOLLOWED
    if 400 <= status_code < 500:
        return OUTCOME_REJECTED
    if 500 <= status_code < 600:
        return OUTCOME_RECEIVER_ERROR
    return OUTCOME_UNEXPECTED_STATUS


def response_facts_line(response: httpx.Response) -> str:
    """The stored line for a receiver's answer: outcome, status and body length, no body text."""
    status = int(response.status_code)
    return f"outcome={delivery_outcome(status)} http_status={status} content_length={len(response.content or b'')}"


def parse_response_facts(value: Any) -> dict[str, Any] | None:
    """The facts of a stored line, or None for anything else (including raw bodies)."""
    match = _FACTS_LINE.match(value) if isinstance(value, str) else None
    if match is None or match.group(1) not in DELIVERY_OUTCOMES:
        return None
    return {
        "outcome": match.group(1),
        "http_status": int(match.group(2)),
        "content_length": int(match.group(3)),
    }


def serialized_response_facts(value: Any) -> tuple[str | None, dict[str, Any] | None]:
    """``(response_body, response_facts)`` for the API: the validated line and its parsed facts."""
    facts = parse_response_facts(value)
    return (value if facts else None), facts


__all__ = [
    "DELIVERY_OUTCOMES",
    "delivery_outcome",
    "parse_response_facts",
    "response_facts_line",
    "serialized_response_facts",
]
