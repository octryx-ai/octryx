"""The decision log — OCSF-like records, filters, pagination, retention, bounded buffer, redaction."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.models import PolicyDecisionLog, SystemConfig
from app.services.policy_engine import decision_log
from app.services.policy_engine.decision_log import (
    RETENTION_CONFIG_KEY,
    clear_decision_buffer,
    dropped_records,
    flush_decision_log,
    pending_records,
    prune_decision_log,
    record_decision,
)
from app.services.policy_engine.engine import EntityRef
from app.services.policy_engine.points import PointQuery
from app.services.policy_engine.runtime import PolicyRuntime
from app.services.policy_engine.shadow import LegacyDecision, PolicyComparison
from app.services.policy_engine.shadow_record import _entry
from app.time_utils import utc_now
from tests.policy_engine_support import BASE, bearer, make_user


def _row(**overrides) -> dict:
    entry = {
        "created_at": utc_now(), "point": "gateway_tool_check", "action": "run_command", "outcome": "mismatch",
        "mode": "shadow", "workspace_id": "ws-1", "principal": "AgentSession::s1", "resource": "Bash: ls",
        "decision": "deny", "legacy_decision": "allow", "legacy_reason": "no_rule_matched",
        "determining": ["workspace:ws-1:tool-rule:x"], "errors": [], "policy_set_digest": "sha256:a",
        "custom_version": None, "schema_version": "2026-10-06.1", "latency_us": 250,
    }
    entry.update(overrides)
    return entry


@pytest.mark.asyncio
async def test_the_api_filters_paginates_and_serializes_ocsf_like(client, db):
    admin = await make_user(db, admin=True)
    for index in range(5):
        record_decision(_row(created_at=utc_now() - timedelta(minutes=index), workspace_id=f"ws-{index % 2}"))
    record_decision(_row(point="seat", action="use_seat", outcome="custom_policy", determining=["custom-1"],
                         workspace_id="ws-9"))
    await flush_decision_log(db)
    await db.commit()
    page = (await client.get(f"{BASE}/decisions?point=gateway_tool_check&limit=2", headers=bearer(admin))).json()
    assert page["total"] == 5 and len(page["items"]) == 2
    item = page["items"][0]
    assert item["class_name"] == "Authorization" and item["actor"] == {"principal": "AgentSession::s1"}
    assert item["legacy"] == {"decision": "allow", "reason": "no_rule_matched"}
    assert item["policy_set"]["schema_version"] == "2026-10-06.1" and item["latency_ms"] == 0.25
    assert (await client.get(f"{BASE}/decisions?workspace_id=ws-1", headers=bearer(admin))).json()["total"] == 2
    custom = (await client.get(f"{BASE}/decisions?policy_id=custom-1", headers=bearer(admin))).json()
    assert [row["point"] for row in custom["items"]] == ["seat"]
    assert (await client.get(f"{BASE}/decisions?outcome=custom_policy", headers=bearer(admin))).json()["total"] == 1
    since = (utc_now() - timedelta(seconds=90)).isoformat()
    # Approval records of the seeded data are in the log too (observability O2); count this test's rows only.
    recent = (await client.get(f"{BASE}/decisions", params={"since": since, "point": "gateway_tool_check"},
                               headers=bearer(admin))).json()
    assert recent["total"] == 2
    assert (await client.get(f"{BASE}/decisions?limit=500", headers=bearer(admin))).status_code == 422


@pytest.mark.asyncio
async def test_retention_prunes_old_rows_and_caps_the_table(db, monkeypatch):
    now = utc_now()
    # The default retention is 365 days (observability O8); approval records of the seeded data are other rows.
    test_rows = select(func.count()).select_from(PolicyDecisionLog).where(PolicyDecisionLog.point == "gateway_tool_check")
    for days in (1, 10, 400):
        record_decision(_row(created_at=now - timedelta(days=days)))
    await flush_decision_log(db, prune=False)
    await prune_decision_log(db, now=now)
    assert (await db.execute(test_rows)).scalar_one() == 2
    db.add(SystemConfig(key=RETENTION_CONFIG_KEY, value="7"))
    await db.flush()
    await prune_decision_log(db, now=now)
    assert (await db.execute(test_rows)).scalar_one() == 1
    monkeypatch.setattr(decision_log, "MAX_ROWS", 2)
    for minutes in range(4):
        record_decision(_row(created_at=now - timedelta(minutes=minutes)))
    await flush_decision_log(db, prune=True)
    remaining = (await db.execute(select(PolicyDecisionLog.created_at))).scalars().all()
    assert len(remaining) == 2 and min(remaining) >= now - timedelta(minutes=1)


@pytest.mark.asyncio
async def test_an_invalid_retention_value_falls_back_to_the_default(db):
    db.add(SystemConfig(key=RETENTION_CONFIG_KEY, value="forever"))
    await db.flush()
    assert await decision_log.retention_days(db) == decision_log.DEFAULT_RETENTION_DAYS == 365


def test_the_buffer_is_bounded_and_counts_drops(monkeypatch):
    clear_decision_buffer()
    for _ in range(decision_log.BUFFER_SIZE + 3):
        record_decision(_row())
    assert pending_records() == decision_log.BUFFER_SIZE and dropped_records() == 3
    clear_decision_buffer()


@pytest.mark.asyncio
async def test_a_failed_flush_keeps_the_records(monkeypatch):
    clear_decision_buffer()
    record_decision(_row())

    def broken():
        raise RuntimeError("db down")

    monkeypatch.setattr("app.db.core.async_session_factory", broken)
    with pytest.raises(RuntimeError):
        await flush_decision_log()
    assert pending_records() == 1
    clear_decision_buffer()


def test_secrets_in_a_command_are_redacted_in_the_record():
    query = PointQuery("gateway_tool_check", "run_command", "ws", EntityRef("User", "u"),
                       ("Bash: curl -H 'Authorization: Bearer abc." + "def.ghi' https://x password=hunter2"), "", (), ())
    entry = _entry(query, LegacyDecision(True), PolicyComparison("mismatch", False), PolicyRuntime(), None)
    assert "hunter2" not in entry["resource"] and ("abc." + "def.ghi") not in entry["resource"]
