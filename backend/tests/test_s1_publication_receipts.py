"""Audience receipts have their shape and state enforced, are consumed once, and a concurrent consume has one winner on PostgreSQL."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.alembic_model_parity_support import ScratchDatabase, migrated_database, requires_postgres
from tests.s1_publication_models_support import (  # noqa: F401
    HASH,
    INTENTS,
    NOW,
    RECEIPTS,
    _insert,
    _intent,
    _refused,
    _seed,
    _update,
    database,
    migrated_template,
)


def _receipt(ids: dict[str, str], **overrides: Any) -> dict[str, Any]:
    row = {
        "id": str(uuid.uuid4()), "challenge_id": uuid.uuid4().hex, "run_id": ids["run"], "node_id": "audience_proof",
        "pass_key": "pass-1", "intent_id": ids["intent"], "publication_card_hash": HASH, "workspace_id": ids["project"],
        "connection_id": "conn-1", "instance": "https://example.invalid/wiki", "source_key": "demo-confluence",
        "page_id": "555", "page_version": 1, "revision_id": "rev-1", "revision_digest": HASH,
        "query_set": [{"assertion": "AC-1"}], "query_set_digest": HASH, "expected_principal_id": ids["audience"],
        "issue_checks": {"role": "reader"}, "state": "issued", "issued_at": NOW,
        "expires_at": NOW + dt.timedelta(hours=1), "updated_at": NOW,
    }
    row.update(overrides)
    return row


def _recorded(ids: dict[str, str], **overrides: Any) -> dict[str, Any]:
    return _receipt(ids, **{"state": "recorded", "recorded_at": NOW, "recorded_by": ids["audience"],
                            "outcome": "positive", "hits": [{"span_id": "s-1", "content_sha256": "b" * 64}],
                            "result_digest": HASH, **overrides})


def _receipt_ids(database: ScratchDatabase) -> dict[str, str]:  # noqa: F811
    ids = database.run(_seed)
    intent = _intent(ids)
    _insert(database, INTENTS, intent)
    ids["intent"] = intent["id"]
    return ids


# --- audience-receipt invariants -----------------------------------------------------------------------------------


def test_receipt_shape_and_state_are_enforced(database: ScratchDatabase) -> None:  # noqa: F811
    ids = _receipt_ids(database)
    first = _receipt(ids)
    _insert(database, RECEIPTS, first)
    _refused(database, RECEIPTS, _receipt(ids, challenge_id=first["challenge_id"]))
    _refused(database, RECEIPTS, _receipt(ids, state="accepted"))
    _refused(database, RECEIPTS, _receipt(ids, expires_at=NOW))
    _refused(database, RECEIPTS, _receipt(ids, state="recorded"))
    _refused(database, RECEIPTS, _recorded(ids, outcome="maybe"))
    _refused(database, RECEIPTS, _receipt(ids, intent_id=None))
    _refused(database, RECEIPTS, _recorded(ids, recorded_by=None))
    _refused(database, RECEIPTS, _recorded(ids, recorded_by=ids["requester"]))
    _refused(database, RECEIPTS, _receipt(ids, state="revoked"))
    # Consumed: only with its time and by the run the challenge was issued for.
    _refused(database, RECEIPTS, _recorded(ids, state="consumed", consumed_by_run_id=ids["run"]))
    _refused(database, RECEIPTS, _recorded(ids, state="consumed", consumed_at=NOW, consumed_by_run_id=ids["other_run"]))
    _refused(database, RECEIPTS, _recorded(ids, consumed_at=NOW, consumed_by_run_id=ids["run"]))


def test_a_receipt_is_consumed_once(database: ScratchDatabase) -> None:  # noqa: F811
    ids = _receipt_ids(database)
    row = _recorded(ids)
    _insert(database, RECEIPTS, row)

    def consume(receipt_id: str) -> int:
        return _update(database, RECEIPTS, [RECEIPTS.c.id == receipt_id, RECEIPTS.c.state == "recorded"],
                       {"state": "consumed", "consumed_at": NOW, "consumed_by_run_id": ids["run"],
                        "state_version": RECEIPTS.c.state_version + 1})

    assert consume(row["id"]) == 1
    assert consume(row["id"]) == 0
    # A second receipt for the same run/node/pass cannot also be consumed.
    second = _recorded(ids)
    _insert(database, RECEIPTS, second)
    with pytest.raises(IntegrityError):
        consume(second["id"])


@requires_postgres
def test_concurrent_consume_has_one_winner_on_postgres(tmp_path: Path) -> None:
    with migrated_database("postgresql", tmp_path) as database:  # noqa: F811
        ids = _receipt_ids(database)
        row = _recorded(ids)
        _insert(database, RECEIPTS, row)

        async def contest() -> list[int]:
            engine = create_async_engine(database.url)
            barrier = asyncio.Barrier(2)

            async def consumer(name: str) -> int:
                async with engine.connect() as connection, connection.begin():
                    await barrier.wait()
                    locked = (await connection.execute(
                        select(RECEIPTS.c.state).where(RECEIPTS.c.id == row["id"]).with_for_update()
                    )).scalar_one()
                    if locked != "recorded":
                        return 0
                    result = await connection.execute(
                        update(RECEIPTS).where(RECEIPTS.c.id == row["id"], RECEIPTS.c.state == "recorded")
                        .values(state="consumed", consumed_at=NOW, consumed_by_run_id=ids["run"],
                                consume_checks={"by": name})
                    )
                    await asyncio.sleep(0.2)
                    return result.rowcount

            try:
                return list(await asyncio.gather(consumer("a"), consumer("b")))
            finally:
                await engine.dispose()

        assert sorted(asyncio.run(contest())) == [0, 1]
