"""The one refusal for deciding an approval that is no longer pending: 409 with a stable code.

A second decision must not answer 400 on the session, sessionless and
"Always" paths while every other "it changed under you" refusal of the API is a 409 (four-eyes).
The phone and the web read the code, not the text, to say "already decided" and re-read their list.
"""

from __future__ import annotations

from fastapi import HTTPException, status

APPROVAL_ALREADY_RESOLVED_CODE = "approval_already_resolved"
APPROVAL_ALREADY_RESOLVED_MESSAGE = "This approval was already decided."


def approval_already_resolved() -> HTTPException:
    """409 for every decision path (session, sessionless, "Always"): the approval was decided before this call."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": APPROVAL_ALREADY_RESOLVED_CODE, "message": APPROVAL_ALREADY_RESOLVED_MESSAGE},
    )


__all__ = ["APPROVAL_ALREADY_RESOLVED_CODE", "APPROVAL_ALREADY_RESOLVED_MESSAGE", "approval_already_resolved"]
