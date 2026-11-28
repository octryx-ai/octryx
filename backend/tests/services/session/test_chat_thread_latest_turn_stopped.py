"""The thread list says when a thread's newest turn was stopped, so it never shows "done"."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event, select

from app.models import Session, TurnTrace, User
from app.services.session.execution_gate import evaluate_execution_gate
from app.services.session.turn_execution_snapshot import (
    RUNTIME_OUTCOME_KEY,
    TURN_EXECUTION_SNAPSHOT_KEY,
    build_turn_execution_snapshot,
    with_runtime_stop,
)
from app.services.session.turn_execution_summary import runtime_outcome_from_trace

BASE = datetime(2026, 10, 4, 12, 0)


def _context() -> dict:
    profile = {
        "version": "execution_profile.v1", "status": "allowed", "profile_id": "direct_chat_safe",
        "decision_source": "direct_chat_safe", "execution_strategy": "direct",
    }
    snapshot = build_turn_execution_snapshot(
        execution_profile=profile, gate=evaluate_execution_gate(profile), session_metadata={}, agent_definition=None,
    )
    return {TURN_EXECUTION_SNAPSHOT_KEY: snapshot} if TURN_EXECUTION_SNAPSHOT_KEY not in snapshot else snapshot


def _stopped(reason: str = "answer_evidence_invented_url") -> dict:
    return with_runtime_stop(_context(), reason)


def _finished() -> dict:
    context = _context()
    context[TURN_EXECUTION_SNAPSHOT_KEY] = {**context[TURN_EXECUTION_SNAPSHOT_KEY], RUNTIME_OUTCOME_KEY: "finished"}
    return context


async def _thread(db, title: str, traces: list[tuple[dict, dict | None]]) -> str:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()), user_id=admin.id, agent_type="diagnosis", status="active", metadata_={"title": title}
    )
    db.add(session)
    await db.flush()
    for minute, (context, raw_output) in enumerate(traces):
        db.add(TurnTrace(
            id=str(uuid.uuid4()), session_id=session.id, context_snapshot_json=context,
            raw_output=raw_output or {}, created_at=BASE + timedelta(minutes=minute),
        ))
    await db.commit()
    return session.id


def test_the_fixtures_read_as_intended_through_the_summary_classifier():
    assert runtime_outcome_from_trace(_stopped(), {}) == "stopped"
    assert runtime_outcome_from_trace(_finished(), {}) == "finished"
    assert runtime_outcome_from_trace(_stopped(), {"error": "boom"}) == "failed"
    assert runtime_outcome_from_trace(_context(), {}) not in {"stopped", "finished", "failed"}


@pytest.mark.asyncio
async def test_only_a_newest_stopped_turn_marks_the_thread(client, auth_headers, db):
    expected = {
        await _thread(db, "Newest stopped", [(_finished(), None), (_stopped(), None)]): True,
        await _thread(db, "Stopped then finished", [(_stopped(), None), (_finished(), None)]): False,
        await _thread(db, "Stopped then still running", [(_stopped(), None), (_context(), None)]): False,
        await _thread(db, "Failed newest", [(_stopped(), {"error": "provider failed"})]): False,
        await _thread(db, "Finished", [(_finished(), None)]): False,
        await _thread(db, "No traces", []): False,
    }
    page = await client.get("/admin/chat/api/thread-groups?project_id=&offset=0&limit=100", headers=auth_headers)
    assert page.status_code == 200
    rows = {row["id"]: row for row in page.json()["sessions"]}
    assert {session_id: rows[session_id]["latestTurnStopped"] for session_id in expected} == expected
    for session_id in expected:
        assert rows[session_id]["latestTurnStopped"] in (True, False)
        assert "context_snapshot_json" not in rows[session_id] and "raw_output" not in rows[session_id]


@pytest.mark.asyncio
async def test_the_newest_stop_carries_its_closed_reason_and_nothing_else_does(client, auth_headers, db):
    expected = {
        await _thread(db, "Evidence stop", [(_finished(), None), (_stopped(), None)]): "answer_evidence_invented_url",
        await _thread(db, "Step stop", [(_stopped("step_tool_required"), None)]): "step_tool_required",
        await _thread(db, "Stopped then finished", [(_stopped(), None), (_finished(), None)]): None,
        await _thread(db, "Failed newest", [(_stopped(), {"error": "provider failed"})]): None,
        await _thread(db, "No traces", []): None,
    }
    page = await client.get("/admin/chat/api/thread-groups?project_id=&offset=0&limit=100", headers=auth_headers)
    rows = {row["id"]: row for row in page.json()["sessions"]}
    assert {session_id: rows[session_id]["latestTurnStopReason"] for session_id in expected} == expected
    for session_id, reason in expected.items():
        assert rows[session_id]["latestTurnStopped"] is (reason is not None)


@pytest.mark.asyncio
async def test_a_page_of_many_threads_reads_turn_traces_once(client, auth_headers, db):
    for index in range(6):
        await _thread(db, f"Stopped {index}", [(_finished(), None), (_stopped("step_stalled"), None)])
    statements: list[str] = []

    def record(_conn, _cursor, statement, *_args):
        if "turn_traces" in statement.lower():
            statements.append(statement)

    # The request shares the test's transaction-bound connection; listen on it (an engine listener added
    # after the connection was checked out would not fire for it).
    connection = (await db.connection()).sync_connection
    event.listen(connection, "before_cursor_execute", record)
    try:
        page = await client.get("/admin/chat/api/thread-groups?project_id=&offset=0&limit=100", headers=auth_headers)
    finally:
        event.remove(connection, "before_cursor_execute", record)
    assert page.status_code == 200
    assert sum(row["latestTurnStopReason"] == "step_stalled" for row in page.json()["sessions"]) == 6
    assert len(statements) == 1, "one window query for the whole page, no per-thread read"
