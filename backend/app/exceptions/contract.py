"""Helpers for attaching and serializing bounded error contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_ERROR_CODE_ATTR = "_octryx_error_code"
_RETRYABLE_ATTR = "_octryx_error_retryable"


@dataclass(frozen=True)
class ErrorContract:
    error_code: str
    retryable: bool


def with_error_contract(exception: Exception, *, error_code: str, retryable: bool) -> Exception:
    setattr(exception, "error_code", error_code)
    setattr(exception, "retryable", retryable)
    setattr(exception, _ERROR_CODE_ATTR, error_code)
    setattr(exception, _RETRYABLE_ATTR, retryable)
    return exception


def get_error_contract(
    exception: object,
    *,
    default_error_code: str = "internal_error",
    default_retryable: bool = False,
) -> ErrorContract:
    if isinstance(exception, dict):
        error_code = str(exception.get("error_code") or default_error_code)
        retryable = bool(exception.get("retryable", default_retryable))
        return ErrorContract(error_code=error_code, retryable=retryable)

    error_code = str(getattr(exception, "error_code", getattr(exception, _ERROR_CODE_ATTR, default_error_code)))
    retryable = bool(getattr(exception, "retryable", getattr(exception, _RETRYABLE_ATTR, default_retryable)))
    return ErrorContract(error_code=error_code, retryable=retryable)


def build_error_response(exception: Exception, *, request_id: str | None = None) -> dict[str, Any]:
    contract = get_error_contract(exception)
    payload: dict[str, Any] = {
        "message": str(exception),
        "error_code": contract.error_code,
        "retryable": contract.retryable,
    }
    if request_id is not None:
        payload["request_id"] = request_id
    return payload
