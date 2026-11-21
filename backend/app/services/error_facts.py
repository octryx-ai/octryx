"""Fixed error facts for responses, stored records and logs.

An exception message can carry provider response bodies, hosts, URLs, tokens or internal paths.
Wherever an error leaves its ``except`` block (an HTTP response, a stored run or delivery record,
an admin payload, a log line) it is reduced to narrow-charset facts: a closed error code chosen by
the caller and the exception class name. The message itself is never kept.
"""

from __future__ import annotations

import re
from typing import Any

UNEXPECTED_ERROR = "unexpected_error"

_SAFE_TYPE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def error_type(exc: BaseException) -> str:
    """The exception class name, or ``Exception`` when the name is outside the narrow charset."""
    name = type(exc).__name__
    return name if _SAFE_TYPE.match(name) else "Exception"


def error_code(code: str) -> str:
    """The caller's closed code, or ``unexpected_error`` when it is outside the narrow charset."""
    return code if _SAFE_CODE.match(code or "") else UNEXPECTED_ERROR


def error_facts(code: str, exc: BaseException) -> dict[str, Any]:
    """``{"error_code": ..., "error_type": ...}`` for JSON responses and stored payloads."""
    return {"error_code": error_code(code), "error_type": error_type(exc)}


def error_text(code: str, exc: BaseException) -> str:
    """The same facts as one string, for text columns and ``detail`` messages."""
    return f"{error_code(code)} error_type={error_type(exc)}"
