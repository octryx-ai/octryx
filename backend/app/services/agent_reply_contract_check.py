"""Runtime helpers of the reply contract: the prompt instruction and the strict reply check.

Pure functions; the wiring belongs to the runtime package, which imports them from here.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from .agent_reply_contract_model import matches_named
from .agent_reply_contract_schema import (
    _SCHEMA_NAME,
    KIND_JSON_OBJECT,
    KIND_TEXT,
    REASON_CONTRACT_INVALID,
    REASON_NOT_JSON,
    REASON_SCHEMA_MISMATCH,
    STATUS_SATISFIED,
    STATUS_VIOLATED,
    ReplyContractError,
    _named_schema,
    normalize_reply_contract,
)


def _type_label(spec: Mapping[str, Any]) -> str:
    if spec["type"] == "array":
        return f"array of {spec['items']['type']}"
    return str(spec["type"])


def render_reply_contract_instruction(contract: Any) -> str | None:
    """The reply-format instruction for a checked contract; ``None`` for text.

    Raises :class:`ReplyContractError` for an invalid contract, so a caller fails closed
    instead of prompting for an unchecked shape. Size is bounded by the contract limits.
    """
    normalized = normalize_reply_contract(contract)
    if normalized["kind"] == KIND_TEXT:
        return None
    schema = normalized["schema"]
    required = set(schema["required"])
    lines = [
        "Reply format (checked): your entire final reply must be exactly one JSON object and nothing else.",
        "Do not add a preface, explanation, Markdown, code fences or trailing text.",
        "Fields:",
    ]
    shape = []
    for name, spec in schema["properties"].items():
        lines.append(f"- {name}: {_type_label(spec)} ({'required' if name in required else 'optional'})")
        shape.append(f'"{name}": <{_type_label(spec)}>')
    lines.append("Shape: {" + ", ".join(shape) + "}")
    return "\n".join(lines)


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate key")
    return dict(pairs)


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("non-finite number")
    return value


def _float_range_int(text: str) -> int:
    """Integers must be representable as floats, like every other JSON number here.

    Otherwise the unchanged IR value check (``math.isfinite``) would overflow on a ``number`` field,
    and an ``integer`` field would accept a number no other consumer can read as a float.
    """
    value = int(text)  # more than 4300 digits already raises ValueError
    try:
        float(value)
    except OverflowError as exc:
        raise ValueError("integer out of float range") from exc
    return value


def _refuse_constant(_name: str) -> Any:
    raise ValueError("non-finite constant")


def _result(status: str, reason: str | None) -> dict[str, Any]:
    return {"kind": KIND_JSON_OBJECT, "status": status, "reason": reason}


def check_reply(contract: Any, reply: Any) -> dict[str, Any] | None:
    """The strict check of a raw final reply against an explicit contract.

    ``None`` for a text contract. Otherwise ``{"kind": "json_object", "status": "satisfied" |
    "violated", "reason": code | None}``:

    - an invalid contract gives ``agent_reply_contract_invalid``;
    - anything but one JSON object gives ``agent_reply_not_json``: fenced text, a preface or
      trailing text, duplicate keys, ``NaN``/``Infinity``, or numbers (integers included)
      out of float range;
    - JSON whose root is not an object, a missing required field or a wrong type gives
      ``agent_reply_schema_mismatch``.

    Whitespace around the object is allowed. The reply is never stripped, unfenced or repaired.
    """
    try:
        normalized = normalize_reply_contract(contract)
    except ReplyContractError:
        return _result(STATUS_VIOLATED, REASON_CONTRACT_INVALID)
    if normalized["kind"] == KIND_TEXT:
        return None
    if not isinstance(reply, str):
        return _result(STATUS_VIOLATED, REASON_NOT_JSON)
    try:
        value = json.loads(
            reply,
            object_pairs_hook=_object_without_duplicates,
            parse_float=_finite_float,
            parse_int=_float_range_int,
            parse_constant=_refuse_constant,
        )
    except (ValueError, OverflowError, RecursionError):
        return _result(STATUS_VIOLATED, REASON_NOT_JSON)
    if not isinstance(value, dict):
        return _result(STATUS_VIOLATED, REASON_SCHEMA_MISMATCH)
    schema = _named_schema(normalized)
    if not matches_named(value, _SCHEMA_NAME, {_SCHEMA_NAME: schema}):
        return _result(STATUS_VIOLATED, REASON_SCHEMA_MISMATCH)
    return _result(STATUS_SATISFIED, None)
