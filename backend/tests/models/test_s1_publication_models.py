"""S1 write intents and audience receipts: Alembic-built schema, DB invariants and the migration round trip."""

from __future__ import annotations

from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select
from sqlalchemy.engine import Connection

from app.models.runtime.documentation_publication import (
    INTENT_ACTIVE_STATES,
    INTENT_POTENTIALLY_SENT_STATES,
    INTENT_SENDABLE_STATES,
    INTENT_STATES,
    INTENT_TRANSITIONS,
    RECEIPT_STATES,
    RECEIPT_TRANSITIONS,
    intent_transition_allowed,
    receipt_transition_allowed,
)
from tests.alembic_model_parity_support import MIGRATION_METADATA, ScratchDatabase
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


def _approved(ids: dict[str, str], **overrides: Any) -> dict[str, Any]:
    return _intent(ids, **{"state": "approved", "decision_id": ids["decision"], "card_hash": HASH, "body_hash": HASH,
                           "approved_at": NOW, **overrides})


def _owned_drift(connection: Connection) -> list:
    owned = {INTENTS.name, RECEIPTS.name}
    context = MigrationContext.configure(
        connection, opts={"compare_type": True, "compare_server_default": False,
                          "include_object": lambda obj, name, kind, _reflected, _other: (
                              name if kind == "table" else obj.table.name) in owned}
    )
    return compare_metadata(context, MIGRATION_METADATA)


def _schema(connection: Connection) -> dict[str, Any]:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if "documentation_write_intents" not in tables:
        return {"tables": tables & {"documentation_write_intents", "audience_receipts"}}
    return {
        "tables": tables & {"documentation_write_intents", "audience_receipts"},
        "intent_checks": {c["name"] for c in inspector.get_check_constraints("documentation_write_intents")},
        "receipt_checks": {c["name"] for c in inspector.get_check_constraints("audience_receipts")},
        "intent_indexes": {i["name"]: bool(i["unique"]) for i in inspector.get_indexes("documentation_write_intents")},
        "receipt_indexes": {i["name"]: bool(i["unique"]) for i in inspector.get_indexes("audience_receipts")},
        "drift": _owned_drift(connection),
    }


def test_transition_maps_are_closed_and_potentially_sent_intents_never_supersede() -> None:
    assert set(INTENT_TRANSITIONS) == set(INTENT_STATES)
    assert all(targets <= set(INTENT_STATES) for targets in INTENT_TRANSITIONS.values())
    assert set(RECEIPT_TRANSITIONS) == set(RECEIPT_STATES)
    for state in INTENT_POTENTIALLY_SENT_STATES:
        assert not intent_transition_allowed(state, "superseded")
        assert not intent_transition_allowed(state, "approved")
    assert {s for s, targets in INTENT_TRANSITIONS.items() if "send_started" in targets} == INTENT_SENDABLE_STATES
    assert {s for s, targets in INTENT_TRANSITIONS.items() if "never_started_certified" in targets} == (
        INTENT_POTENTIALLY_SENT_STATES
    )
    assert set(INTENT_ACTIVE_STATES) == set(INTENT_STATES) - {"sent_confirmed", "superseded"}
    assert receipt_transition_allowed("recorded", "consumed")
    assert not receipt_transition_allowed("issued", "consumed")
    assert not receipt_transition_allowed("consumed", "consumed")


def test_no_token_or_credential_columns() -> None:
    for table in (INTENTS, RECEIPTS):
        for column in table.columns:
            assert not any(word in column.name for word in ("token", "secret", "credential", "password", "cookie"))


def test_duplicate_operation_id_and_marker_are_refused(database: ScratchDatabase) -> None:  # noqa: F811
    ids = database.run(_seed)
    first = _intent(ids)
    _insert(database, INTENTS, first)
    _refused(database, INTENTS, _intent(ids, run_id=ids["other_run"], operation_id=first["operation_id"]))
    _refused(database, INTENTS, _intent(ids, run_id=ids["other_run"], marker=first["marker"]))


def test_one_active_intent_per_run_and_slot_survives_a_retried_pass(database: ScratchDatabase) -> None:  # noqa: F811
    ids = database.run(_seed)
    first = _approved(ids)
    _insert(database, INTENTS, first)
    _refused(database, INTENTS, _intent(ids, reserved_pass_key="pass-2"))
    _insert(database, INTENTS, _intent(ids, run_id=ids["other_run"]))
    _insert(database, INTENTS, _intent(ids, slot="other_slot"))
    assert _update(database, INTENTS, [INTENTS.c.id == first["id"], INTENTS.c.state == "approved"],
                   {"state": "superseded", "superseded_at": NOW}) == 1
    _insert(database, INTENTS, _intent(ids, reserved_pass_key="pass-2"))


def test_invalid_states_and_shapes_are_refused(database: ScratchDatabase) -> None:  # noqa: F811
    ids = database.run(_seed)
    _refused(database, INTENTS, _intent(ids, state="unknown"))
    _refused(database, INTENTS, _intent(ids, operation="upsert"))
    _refused(database, INTENTS, _intent(ids, page_id="555"))
    _refused(database, INTENTS, _intent(ids, expected_version=2))
    _refused(database, INTENTS, _intent(ids, operation="update", page_id="555", base_version=3, expected_version=3))
    _refused(database, INTENTS, _intent(ids, state="approved", card_hash=HASH, body_hash=HASH, approved_at=NOW))
    _refused(database, INTENTS, _approved(ids, claimed_by="worker-1", claimed_at=NOW))
    _refused(database, INTENTS, _approved(ids, state="send_started"))
    _refused(database, INTENTS, _approved(ids, state="sent_confirmed", claimed_by="w", claimed_at=NOW,
                                          send_started_at=NOW))
    _refused(database, INTENTS, _approved(ids, state="never_started_certified"))
    _insert(database, INTENTS, _intent(ids, operation="update", page_id="555", parent_id=None, base_version=3,
                                       expected_version=4))


def test_one_claimed_sender_per_intent(database: ScratchDatabase) -> None:  # noqa: F811
    ids = database.run(_seed)
    row = _approved(ids)
    _insert(database, INTENTS, row)

    def claim(worker: str) -> int:
        return _update(database, INTENTS,
                       [INTENTS.c.id == row["id"], INTENTS.c.state.in_(sorted(INTENT_SENDABLE_STATES)),
                        INTENTS.c.claimed_by.is_(None)],
                       {"state": "send_started", "claimed_by": worker, "claimed_at": NOW, "send_started_at": NOW,
                        "state_version": INTENTS.c.state_version + 1})

    assert claim("worker-1") == 1
    assert claim("worker-2") == 0
    assert database.run(lambda c: c.execute(select(INTENTS.c.claimed_by).where(INTENTS.c.id == row["id"])).scalar_one()
                        ) == "worker-1"
    _refused(database, INTENTS, _intent(ids, reserved_pass_key="pass-2"))
