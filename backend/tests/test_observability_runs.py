"""Runs over turn_traces + tool_calls (all sources, SQL read model, admin-only)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agent.runtime.trace_runtime import persist_turn_trace
from app.models import AuditLog, Message, ToolCall, TurnTrace, UsageEvent
from app.services.devices.run_trace import record_device_turn
from app.services.observability.run_summary import gateway_run_summary, run_summary_fields, turn_outcome
from app.services.observability.runs_read_model import list_runs, run_metrics
from app.services.request_context import reset_current_request_id, set_current_request_id
from app.time_utils import utc_now
from tests.observability_support import add_trace, admin_user, call_as, session_for, user_with_role, workspace


async def _in_app_turn(db, session, request_id: str, raw_outputs: list[dict]) -> None:
    token = set_current_request_id(request_id)
    try:
        for raw in raw_outputs:
            await persist_turn_trace(
                db=db, session_id=session.id, message_id=None, provider="bedrock", model="model-a",
                input_messages=[{"role": "user", "content": "hello"}],
                context_snapshot={"agent": {"name": "Code review"}}, tool_trace=[], raw_output=raw,
                usage={"input_tokens": 10, "output_tokens": 2},
            )
    finally:
        reset_current_request_id(token)


def test_outcome_comes_only_from_explicit_fields():
    assert turn_outcome({"content": "Hi"}) == "completed"
    assert turn_outcome({"gate_outcome": {"gate": "execution_gate", "status": "denied"}}) == "blocked"
    assert turn_outcome({"gate_outcome": {"gate": "execution_gate", "status": "needs_approval"}}) == "needs_approval"
    assert turn_outcome({"status": "waiting_approval"}) == "needs_approval"
    assert turn_outcome({"error": "boom"}) == "failed"
    assert turn_outcome({}, {"refused_reason": "alias_denied"}) == "blocked"
    assert turn_outcome({}, {"upstream_status": 529}) == "failed"
    # A provider name or a "source" string never decides.
    assert turn_outcome({"source": "execution_gate", "profile_status": "needs_clarification"}) == "completed"


@pytest.mark.asyncio
async def test_an_in_app_run_groups_its_steps_and_counts_its_tool_calls_and_cost(db):
    admin = await admin_user(db)
    project = await workspace(db)
    session = await session_for(db, admin, project=project)
    request_id = f"req-{uuid.uuid4().hex[:12]}"
    await _in_app_turn(db, session, request_id, [{"content": "step 1"}, {"error": "tool loop failed"}])
    for status in ("success", "error", "denied_by_policy"):
        db.add(ToolCall(session_id=session.id, tool_name="repository.search", status=status, request_id=request_id))
    db.add(UsageEvent(session_id=session.id, user_id=admin.id, provider="bedrock", model="model-a", tokens_in=10,
                      cost=Decimal("0"), cost_status="missing_pricing", request_id=request_id))
    db.add(UsageEvent(session_id=session.id, user_id=admin.id, provider="bedrock", model="model-b", tokens_in=10,
                      cost=Decimal("0.25"), cost_status="catalog_pricing", request_id=request_id))
    await db.commit()

    page = await list_runs(db, project_id=project.id)

    assert page["total"] == 1
    run = page["items"][0]
    assert run["run_key"] == f"req:{request_id}"
    assert (run["source"], run["outcome"], run["steps"]) == ("chat", "failed", 2)
    assert (run["tool_count"], run["tool_failed"]) == (3, 2)
    assert run["tool_count"] == len((await db.execute(
        select(ToolCall).where(ToolCall.request_id == request_id))).scalars().all())
    assert (run["cost"], run["cost_state"]) == (0.25, "unpriced")
    assert run["agent_label"] == "Code review"
    assert run["duration_ms"] is not None and run["duration_ms"] >= 0
    assert run["workspace_name"] == project.name


@pytest.mark.asyncio
async def test_gateway_and_device_runs_are_listed_with_their_source(db):
    admin = await admin_user(db)
    project = await workspace(db)
    gateway_session = await session_for(db, admin, origin="model_gateway", project=project)
    for _ in range(2):
        add_trace(db, TurnTrace(
            session_id=gateway_session.id, provider="litellm_gateway", model="alias",
            context_snapshot_json={"source": "model_gateway", "claude_session_id": "cs-1"}, raw_output={},
            usage_json={"duration_ms": 1200},
        ), gateway_run_summary(session_id=gateway_session.id, raw_output={}, usage={}, duration_ms=1200,
                               client_context={"claude_session_id": "cs-1"}))
    device_session = await session_for(db, admin, origin="device_chat", project=project)
    db.add(Message(session_id=device_session.id, role="user", content="run the tests",
                   created_at=utc_now() - timedelta(seconds=30)))
    await db.flush()
    job = SimpleNamespace(id="job-1", turn_id="turn-1", session_id=device_session.id, profile="governed",
                          model="claude-model", turn_model=None, turn_count=1)
    await record_device_turn(db, job, "turn_finished", {"status": "success", "cost_usd": 0.12})
    await db.commit()

    page = await list_runs(db, project_id=project.id)
    by_source = {item["source"]: item for item in page["items"]}

    assert set(by_source) == {"gateway", "device"}
    assert by_source["gateway"]["steps"] == 2
    assert by_source["gateway"]["agent_label"] == "Claude Code (gateway)"
    assert by_source["device"]["outcome"] == "completed"
    assert by_source["device"]["cost_state"] == "not_billed"
    assert by_source["device"]["duration_ms"] >= 29_000
    assert (await list_runs(db, project_id=project.id, source="device"))["total"] == 1
    assert (await list_runs(db, project_id=project.id, outcome="failed"))["total"] == 0
    assert (await list_runs(db, project_id=project.id, query="claude code (gateway)"))["total"] == 1


@pytest.mark.asyncio
async def test_runs_outside_the_window_are_not_listed_and_pages_are_bounded(db):
    admin = await admin_user(db)
    project = await workspace(db)
    session = await session_for(db, admin, project=project)
    for index in range(3):
        await _in_app_turn(db, session, f"req-page-{index}-{uuid.uuid4().hex[:6]}", [{"content": "ok"}])
    add_trace(db, TurnTrace(session_id=session.id, provider="p", model="m", raw_output={},
                            created_at=utc_now() - timedelta(days=3)),
              run_summary_fields(run_key="req:old", raw_output={}))
    await db.commit()

    first = await list_runs(db, project_id=project.id, page_size=2)
    second = await list_runs(db, project_id=project.id, page_size=2, page=2)

    assert first["total"] == 3 and len(first["items"]) == 2 and len(second["items"]) == 1
    assert (await list_runs(db, project_id=project.id, window_hours=168))["total"] == 4
    metrics = await run_metrics(db)
    assert metrics["by_outcome"]["completed"] >= 3


@pytest.mark.asyncio
async def test_runs_api_is_admin_only_and_the_content_read_is_audited_and_redacted(client, db):
    admin = await admin_user(db)
    viewer = await user_with_role(db, "viewer")
    session = await session_for(db, admin)
    request_id = f"req-{uuid.uuid4().hex[:12]}"
    await _in_app_turn(db, session, request_id, [{"content": ("token api_key=sk-li" + "ve-abcdefghijklmnop0123")}])
    await db.commit()
    run_key = f"req:{request_id}"

    for method, path in (("GET", "/api/v1/observability/runs"),
                         ("POST", f"/api/v1/observability/runs/content?run_key={run_key}")):
        assert (await call_as(client, method, path, viewer)).status_code == 403
    listed = await call_as(client, "GET", "/api/v1/observability/runs", admin)
    assert listed.status_code == 200 and listed.json()["total"] >= 1
    detail = await call_as(client, "GET", f"/api/v1/observability/runs/detail?run_key={run_key}", admin)
    assert detail.status_code == 200 and detail.json()["steps"][0]["model"] == "model-a"
    assert "content" not in str(detail.json()["steps"])
    assert detail.json()["viewer_is_owner"] is True
    other_admin = await user_with_role(db, "admin")
    seen_by_other = await call_as(client, "GET", f"/api/v1/observability/runs/detail?run_key={run_key}", other_admin)
    assert seen_by_other.json()["viewer_is_owner"] is False, "chat state is owner-only: no link for another admin"
    missing = await call_as(client, "GET", "/api/v1/observability/runs/detail?run_key=req:none", admin)
    assert missing.status_code == 404

    content = await call_as(client, "POST", f"/api/v1/observability/runs/content?run_key={run_key}", admin)

    assert content.status_code == 200
    assert ("sk-li" + "ve-abcdefghijklmnop0123") not in content.text
    audit = (await db.execute(select(AuditLog).where(
        AuditLog.action == "observability.run.content_viewed", AuditLog.resource_id == run_key))).scalars().all()
    assert len(audit) == 1 and audit[0].user_id == admin.id
    metrics = await call_as(client, "GET", "/metrics", admin)
    assert metrics.status_code == 200 and "# TYPE octryx_agent_turns_total counter" in metrics.text
