"""Jira's own explanation of a refused query, for tools and the Secure Work intake."""

from __future__ import annotations

import httpx

CODE_JQL_INVALID = "jql_invalid"
MAX_MESSAGE_CHARS = 500


def jql_error_message(response: httpx.Response) -> str:
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
