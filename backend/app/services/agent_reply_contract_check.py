"""Runtime helpers of the reply contract: the prompt instruction and the strict reply check."""

from __future__ import annotations

import json
import math
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
from .agent_reply_contract_types import ReplyCheck


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
    # Integers must be representable as floats, like every other JSON number here.
    value = int(text)  # more than 4300 digits already raises ValueError
    try:
        float(value)
    except OverflowError as exc:
        raise ValueError("integer out of float range") from exc
    return value


def _refuse_constant(_name: str) -> Any:
    raise ValueError("non-finite constant")


def _result(status: str, reason: str | None) -> ReplyCheck:
    return {"kind": KIND_JSON_OBJECT, "status": status, "reason": reason}


def check_reply(contract: Any, reply: Any) -> ReplyCheck | None:
    # Never stripped, unfenced or repaired: anything but exactly one JSON object is ``agent_reply_not_json``.
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
