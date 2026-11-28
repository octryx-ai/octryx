"""The one refusal for deciding an approval that is no longer pending: 409 with a stable code."""

from __future__ import annotations

from fastapi import HTTPException, status

APPROVAL_ALREADY_RESOLVED_CODE = "approval_already_resolved"
APPROVAL_ALREADY_RESOLVED_MESSAGE = "This approval was already decided."


def approval_already_resolved() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": APPROVAL_ALREADY_RESOLVED_CODE, "message": APPROVAL_ALREADY_RESOLVED_MESSAGE},
    )


__all__ = ["APPROVAL_ALREADY_RESOLVED_CODE", "APPROVAL_ALREADY_RESOLVED_MESSAGE", "approval_already_resolved"]
