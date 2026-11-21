"""Input rules of a board post: body, options and optional texts are bounded, and no secret is stored."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ..model_gateway.inbound.secret_scan import contains_secret
from .envelope import KIND_DECISION_REQUEST

MAX_BODY_BYTES = 8 * 1024
MAX_OPTIONS = 10
MAX_OPTION_CHARS = 200
CODE_SECRET_DETECTED = "secret_detected"


def _refuse(detail: object, status: int = 422) -> HTTPException:
    return HTTPException(status_code=status, detail=detail)


def _optional_text(value: Any, name: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise _refuse(f"{name} must be a string")
    return value.strip() or None


def body_from(value: Any, *, required: bool = True) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise _refuse("body must be a string")
    if required and not value.strip():
        raise _refuse("body is required")
    if len(value.encode("utf-8")) > MAX_BODY_BYTES:
        raise _refuse(f"body must be at most {MAX_BODY_BYTES} bytes")
    return value


def options_from(value: Any, kind: str) -> list[str]:
    if value is None or value == []:
        return []
    if kind != KIND_DECISION_REQUEST:
        raise _refuse("options are only allowed on a decision_request")
    if not isinstance(value, list) or len(value) > MAX_OPTIONS:
        raise _refuse(f"options must be a list of at most {MAX_OPTIONS} entries")
    if any(not isinstance(entry, str) or not entry.strip() or len(entry) > MAX_OPTION_CHARS for entry in value):
        raise _refuse(f"each option must be 1 to {MAX_OPTION_CHARS} characters")
    return [entry.strip() for entry in value]


def refuse_secrets(*texts: str | None) -> None:
    if any(text and contains_secret(text) for text in texts):
        raise _refuse({"code": CODE_SECRET_DETECTED})
