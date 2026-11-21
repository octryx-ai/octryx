"""Observability O8: one capture policy at storage, retention defaults, owner view, device chunk compaction."""

from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agent.core.runtime.trace_runtime import persist_turn_trace
from app.models import ConnectorHealthLog, DeviceJobEvent, RetentionPolicy, TurnTrace
from app.services.devices.run_trace import compact_finished_turn_text
from app.services.observability.run_owner_view import HIDDEN_NOTE, run_details_for_viewer
from app.services.privacy import apply_retention_policies
from app.services.trace_gate_outcome import gate_outcome_marker
from app.time_utils import utc_now
from tests.observability_support import admin_user, run_summary, session_for, workspace

SECRET = ("api_ke" + "y=sk-live-abcdefghijklmnopqrstu0123")


async def _trace(db, session, raw_output):
    return await persist_turn_trace(
        db=db, session_id=session.id, message_id=None, provider="bedrock", model="m",
        input_messages=[{"role": "user", "content": f"deploy with {SECRET}"}],
        context_snapshot={"request_id": f"req-{uuid.uuid4().hex[:6]}", "system_prompt": "platform rules"},
        tool_trace=[{"tool_name": "bash", "result": {"stdout": SECRET}}], raw_output=raw_output, usage={},
    )


@pytest.mark.asyncio
async def test_standard_capture_redacts_secrets_and_minimal_stores_metadata_only(db):
    admin = await admin_user(db)
    standard = await session_for(db, admin, project=await workspace(db))
    minimal_project = await workspace(db)
    minimal_project.config = {"trace_capture": {"mode": "minimal"}}
    minimal = await session_for(db, admin, project=minimal_project)

    kept = await _trace(db, standard, {"content": f"done {SECRET}"})
    blocked = await _trace(db, minimal, {"content": "secret text", **gate_outcome_marker(
        gate="execution_gate", label="execution gate", status="denied", reason="not allowed")})
    await db.commit()

    assert "sk-live-abcdefghijklmnopqrstu0123" not in str(
        [kept.input_messages_json, kept.tool_trace_json, kept.raw_output])
    assert kept.input_messages_json and kept.raw_output.get("content")
    assert blocked.input_messages_json == [] and blocked.tool_trace_json == []
    assert "content" not in blocked.raw_output and blocked.raw_output["gate_outcome"]["gate"] == "execution_gate"
    assert (await run_summary(db, blocked.id)).outcome == "blocked", "the summary is computed before capture applies"
    assert "system_prompt" not in blocked.context_snapshot_json


def test_owners_do_not_see_platform_prompts_admins_do():
    payload = {"contextSnapshot": {"system_prompt": "rules", "memory_prompt": "mem", "request_id": "r",
                                   "system_context": {"platform": "facts"},
                                   "current_step": {"name": "Review", "instructions": "platform step rules"}},
               "inputMessages": [{"role": "system", "content": "rules"}, {"role": "user", "content": "hi"}]}
    owner = run_details_for_viewer(payload, is_admin=False)
    assert owner["contextSnapshot"]["system_prompt"] == HIDDEN_NOTE and owner["contextSnapshot"]["request_id"] == "r"
    assert owner["contextSnapshot"]["system_context"] == {}
    assert owner["contextSnapshot"]["current_step"] == {"name": "Review", "instructions": HIDDEN_NOTE}
    assert owner["inputMessages"] == [{"role": "system", "content": HIDDEN_NOTE}, {"role": "user", "content": "hi"}]
    assert run_details_for_viewer(payload, is_admin=True) is payload


@pytest.mark.asyncio
async def test_retention_reduces_old_run_content_and_drops_old_connection_checks(db):
    admin = await admin_user(db)
    session = await session_for(db, admin)
    old = await _trace(db, session, {"content": "old"})
    old.created_at = utc_now() - timedelta(days=40)
    db.add(ConnectorHealthLog(connector_name="jira-old", project_id="", status="ok",
                              checked_at=utc_now() - timedelta(days=10)))
    for entity, days, action in (("turn_trace_content", 30, "anonymize"), ("connector_health_log", 7, "delete")):
        if not (await db.execute(select(RetentionPolicy).where(RetentionPolicy.entity_type == entity))).first():
            db.add(RetentionPolicy(entity_type=entity, ttl_days=days, action=action, is_active=True))
    await db.commit()

    await apply_retention_policies(db)

    trace = await db.get(TurnTrace, old.id)
    await db.refresh(trace)
    assert trace.input_messages_json == [] and trace.raw_output == {"retention": "content removed"}
    assert (await run_summary(db, trace.id)).outcome == "completed", "the run itself stays"
    assert (await db.execute(select(ConnectorHealthLog).where(
        ConnectorHealthLog.connector_name == "jira-old"))).first() is None


@pytest.mark.asyncio
async def test_a_finished_device_turn_keeps_its_text_and_drops_the_chunks(db):
    job = SimpleNamespace(id=f"job-{uuid.uuid4().hex[:8]}", turn_id="t1")
    for seq, kind in enumerate(("text_delta", "text_delta", "tool_use", "text"), start=1):
        db.add(DeviceJobEvent(job_id=job.id, seq=seq, type="job_event", body={"turn_id": "t1", "kind": kind}))
    await db.flush()

    assert await compact_finished_turn_text(db, job) == 2
    kinds = [event.body["kind"] for event in (await db.execute(
        select(DeviceJobEvent).where(DeviceJobEvent.job_id == job.id).order_by(DeviceJobEvent.seq))).scalars()]
    assert kinds == ["tool_use", "text"]


@pytest.mark.asyncio
async def test_many_chunks_are_deleted_in_batches_below_the_bind_limit(db, monkeypatch):
    # 33'788 chunks in one DELETE would exceed asyncpg's 32767 parameters and loop the device channel.
    from app.services.devices import run_trace

    monkeypatch.setattr(run_trace, "DELETE_BATCH", 3)
    statements = []
    execute = db.execute

    async def counting(statement, *args, **kwargs):
        if getattr(statement, "is_delete", False):
            statements.append(statement)
        return await execute(statement, *args, **kwargs)

    monkeypatch.setattr(db, "execute", counting)
    job = SimpleNamespace(id=f"job-{uuid.uuid4().hex[:8]}", turn_id="t1")
    kinds = ["text_delta"] * 7 + ["text"]
    for seq, kind in enumerate(kinds, start=1):
        db.add(DeviceJobEvent(job_id=job.id, seq=seq, type="job_event", body={"turn_id": "t1", "kind": kind}))
    await db.flush()

    assert await compact_finished_turn_text(db, job) == 7
    assert len(statements) == 3, "7 ids in batches of 3"
    left = [event.body["kind"] for event in (await execute(
        select(DeviceJobEvent).where(DeviceJobEvent.job_id == job.id))).scalars()]
    assert left == ["text"]
