"""Product Run identity stamped onto a turn's execution snapshot."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from ..session.turn_execution_snapshot import TURN_EXECUTION_SNAPSHOT_KEY

PRODUCT_RUN_STAMP_KEY = "product_run"
PRODUCT_RUN_STAMP_VERSION = "product_run_stamp.v1"
STAMP_BOUND = "bound"
STAMP_UNSCOPED = "unscoped"
_STAMP_STATUSES = frozenset({STAMP_BOUND, STAMP_UNSCOPED})
_MAX_ATTEMPT_NUMBER = 1_000_000

StampReadStatus = Literal["bound", "unscoped", "missing", "malformed"]


def _canonical_uuid(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return None
    return str(parsed) if str(parsed) == value else None


def bound_stamp(*, run_id: str, attempt_id: str, attempt_number: int, origin: str) -> dict[str, Any]:
    if _canonical_uuid(run_id) is None or _canonical_uuid(attempt_id) is None:
        raise ValueError("product run stamp requires canonical UUID ids")
    if type(attempt_number) is not int or not 1 <= attempt_number <= _MAX_ATTEMPT_NUMBER:
        raise ValueError("product run stamp requires a positive attempt number")
    return {
        "version": PRODUCT_RUN_STAMP_VERSION,
        "status": STAMP_BOUND,
        "run_id": run_id,
        "attempt_id": attempt_id,
        "attempt_number": attempt_number,
        "origin": origin,
    }


def unscoped_stamp(*, origin: str) -> dict[str, Any]:
    return {"version": PRODUCT_RUN_STAMP_VERSION, "status": STAMP_UNSCOPED, "origin": origin}


@dataclass(frozen=True, slots=True)
class ProductRunStampRead:
    status: StampReadStatus
    run_id: str | None = None
    attempt_id: str | None = None
    attempt_number: int | None = None
    origin: str | None = None


def read_product_run_stamp(context_snapshot: Any) -> ProductRunStampRead:
    context = context_snapshot if isinstance(context_snapshot, dict) else {}
    snapshot = context.get(TURN_EXECUTION_SNAPSHOT_KEY)
    if not isinstance(snapshot, dict) or PRODUCT_RUN_STAMP_KEY not in snapshot:
        return ProductRunStampRead("missing")
    raw = snapshot[PRODUCT_RUN_STAMP_KEY]
    if not isinstance(raw, dict) or raw.get("version") != PRODUCT_RUN_STAMP_VERSION:
        return ProductRunStampRead("malformed")
    status = raw.get("status")
    origin = raw.get("origin") if isinstance(raw.get("origin"), str) else None
    if status not in _STAMP_STATUSES or origin is None:
        return ProductRunStampRead("malformed")
    if status == STAMP_UNSCOPED:
        if any(key in raw for key in ("run_id", "attempt_id", "attempt_number")):
            return ProductRunStampRead("malformed")
        return ProductRunStampRead(STAMP_UNSCOPED, origin=origin)
    run_id = _canonical_uuid(raw.get("run_id"))
    attempt_id = _canonical_uuid(raw.get("attempt_id"))
    number = raw.get("attempt_number")
    if run_id is None or attempt_id is None or type(number) is not int or not 1 <= number <= _MAX_ATTEMPT_NUMBER:
        return ProductRunStampRead("malformed")
    return ProductRunStampRead(STAMP_BOUND, run_id, attempt_id, number, origin)


__all__ = [
    "PRODUCT_RUN_STAMP_KEY",
    "PRODUCT_RUN_STAMP_VERSION",
    "STAMP_BOUND",
    "STAMP_UNSCOPED",
    "ProductRunStampRead",
    "StampReadStatus",
    "bound_stamp",
    "read_product_run_stamp",
    "unscoped_stamp",
]
