"""Contract of the Product Run stamp on a turn's execution snapshot (the binding writes it, the trace reads it)."""

from __future__ import annotations

import uuid

import pytest

from app.services.product_run.turn_stamp import (
    PRODUCT_RUN_STAMP_KEY,
    bound_stamp,
    read_product_run_stamp,
    unscoped_stamp,
)
from app.services.session.turn_execution_snapshot import TURN_EXECUTION_SNAPSHOT_KEY


def _context(stamp):
    return {TURN_EXECUTION_SNAPSHOT_KEY: {"version": "x", PRODUCT_RUN_STAMP_KEY: stamp}}


def test_bound_and_unscoped_stamps_round_trip() -> None:
    run_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
    read = read_product_run_stamp(
        _context(bound_stamp(run_id=run_id, attempt_id=attempt_id, attempt_number=1, origin="chat_turn"))
    )
    assert (read.status, read.run_id, read.attempt_id, read.attempt_number) == ("bound", run_id, attempt_id, 1)
    assert read_product_run_stamp(_context(unscoped_stamp(origin="chat_turn"))).status == "unscoped"


@pytest.mark.parametrize(
    ("context", "status"),
    [
        (None, "missing"),
        ({TURN_EXECUTION_SNAPSHOT_KEY: {"version": "x"}}, "missing"),
        (_context({"version": "other", "status": "bound"}), "malformed"),
        (_context({"version": "product_run_stamp.v1", "status": "bound", "origin": "chat_turn",
                   "run_id": "RUN", "attempt_id": str(uuid.uuid4()), "attempt_number": 1}), "malformed"),
        (_context({"version": "product_run_stamp.v1", "status": "unscoped", "origin": "chat_turn",
                   "run_id": str(uuid.uuid4())}), "malformed"),
        (_context({"version": "product_run_stamp.v1", "status": "completed", "origin": "chat_turn"}), "malformed"),
    ],
)
def test_off_contract_stamps_are_never_bound(context, status) -> None:
    assert read_product_run_stamp(context).status == status


def test_bound_stamp_refuses_non_canonical_ids() -> None:
    with pytest.raises(ValueError):
        bound_stamp(run_id=str(uuid.uuid4()).upper(), attempt_id=str(uuid.uuid4()), attempt_number=1, origin="chat_turn")
