"""Fixed error facts for responses, stored records and logs. An exception message can carry bodies, hosts, tokens or
paths, so it leaves its ``except`` block only as narrow-charset facts."""

from __future__ import annotations

import re
from typing import Any

UNEXPECTED_ERROR = "unexpected_error"

_SAFE_TYPE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def error_type(exc: BaseException) -> str:
    # A name outside the narrow charset becomes ``Exception``.
    name = type(exc).__name__
    return name if _SAFE_TYPE.match(name) else "Exception"


def error_code(code: str) -> str:
    # A code outside the narrow charset becomes ``unexpected_error``.
    return code if _SAFE_CODE.match(code or "") else UNEXPECTED_ERROR


def error_facts(code: str, exc: BaseException) -> dict[str, Any]:
    return {"error_code": error_code(code), "error_type": error_type(exc)}


def error_text(code: str, exc: BaseException) -> str:
    """The same facts as one string, for text columns and ``detail`` messages."""
    return f"{error_code(code)} error_type={error_type(exc)}"
