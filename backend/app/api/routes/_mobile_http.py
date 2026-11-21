"""Shared answers of the Octryx Mobile route modules."""

from __future__ import annotations

from fastapi.responses import JSONResponse

_NO_STORE = {"cache-control": "no-store"}


def _refusal(reason: str, status: int, *, state: str = "denied") -> JSONResponse:
    return JSONResponse({"state": state, "reason": reason}, status_code=status, headers=_NO_STORE)
