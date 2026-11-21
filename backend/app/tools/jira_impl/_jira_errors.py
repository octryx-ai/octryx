"""Jira's own explanation of a refused query, for tools and the Secure Work intake.

A 400 from a Jira search is a query problem (an invalid JQL, or on Cloud an unbounded one). The
answer's ``errorMessages``/``errors`` are Jira's own words about the query: they carry no secret, no
header and no other body, so they are passed on, bounded, under the fixed code ``jql_invalid``.
"""

from __future__ import annotations

import httpx

CODE_JQL_INVALID = "jql_invalid"
MAX_MESSAGE_CHARS = 500


def jql_error_message(response: httpx.Response) -> str:
    """Jira's messages of a refused query, joined and bounded; a fixed text when it gave none."""
    messages: list[str] = []
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        messages = [str(message) for message in (body.get("errorMessages") or []) if str(message).strip()]
        errors = body.get("errors")
        if isinstance(errors, dict):
            messages.extend(f"{key}: {value}" for key, value in errors.items())
    return ("; ".join(messages) or "Jira rejected the query")[:MAX_MESSAGE_CHARS]


__all__ = ["CODE_JQL_INVALID", "jql_error_message"]
