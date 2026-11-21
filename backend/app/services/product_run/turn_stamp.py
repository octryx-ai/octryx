"""Product Run identity stamped onto a turn's execution snapshot.

The Chat binding opens a Run/Attempt around the turn and stamps its
identity into the bound turn execution snapshot under :data:`PRODUCT_RUN_STAMP_KEY`,
so every ``TurnTrace`` of the turn carries it. The Turn Execution Summary
reads the stamp back and resolves the Run/Attempt *only* through it; it never
looks up "the latest run of the session".

The stamp holds identity only. The attempt's state and end reason are read
from the database at summary time, so a stamp can never claim an outcome.

Stamp statuses (closed):

* ``bound``    - the turn ran inside a Product Run; ids are present;
* ``unscoped`` - the session has no resolvable Workspace, so no run was opened
  and ids are absent.

A trace without a stamp reads as ``missing`` (a ``run_agent`` caller that passes no ``run_origin``), and
anything off-contract reads as ``malformed``; neither is ever treated as bound.
"""

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
    """Stamp for a turn bound to a Run/Attempt; ids must be canonical UUID strings."""
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
    """Stamp for a turn whose session has no resolvable Workspace (no run opened)."""
    return {"version": PRODUCT_RUN_STAMP_VERSION, "status": STAMP_UNSCOPED, "origin": origin}


@dataclass(frozen=True, slots=True)
class ProductRunStampRead:
    status: StampReadStatus
    run_id: str | None = None
    attempt_id: str | None = None
    attempt_number: int | None = None
    origin: str | None = None


def read_product_run_stamp(context_snapshot: Any) -> ProductRunStampRead:
    """Read the stamp from a trace's ``context_snapshot`` and re-validate it."""
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
