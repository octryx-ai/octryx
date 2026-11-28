"""One decision timeline for every gate, the approval lifecycle and the content policies."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agent.runtime.trace_runtime import persist_turn_trace
from app.models import PolicyDecisionCounter
from app.services.approval.request_service import ensure_approval_request
from app.services.approval.resolution_service import resolve_approval_request
from app.services.content_security.model_call_scope import model_call_scope, workspace_call
from app.services.decisions.devices import record_device_dispatch
from app.services.decisions.flusher import flush_allow_counts
from app.services.decisions.timeline import decisions_today, get_decision, list_decisions
from app.services.decisions.tool_dispatch import record_tool_dispatch
from app.services.policy_engine.decision_log import clear_decision_buffer, flush_decision_log
from app.services.trace_gate_outcome import gate_outcome_marker
from tests.content_security_support import RecordingProvider
from tests.observability_support import admin_user, call_as, session_for, user_with_role, workspace


async def _flush(db) -> None:
    await flush_decision_log(db, prune=False)
    await flush_allow_counts(db)
    await db.commit()


@pytest.fixture(autouse=True)
def _clean_buffer():
    clear_decision_buffer()
    yield
    clear_decision_buffer()


@pytest.mark.asyncio
async def test_a_refused_tool_call_is_a_decision_and_an_allowed_one_is_counted(db):
    admin = await admin_user(db)
    project = await workspace(db)
    session = await session_for(db, admin, project=project)
    context = SimpleNamespace(user_id=admin.id, project_ids=[project.id], session_id=session.id, request_id="req-o2")
    blocked = {"error": "denied", "tool_execution": {"category": "denied_by_policy", "policy": "tool_policy",
                                                    "reason": "tool_disabled_for_workspace"}}
    record_tool_dispatch("bash", context, blocked)
    record_tool_dispatch("mcp_tickets_delete", context, {"tool_execution": {"policy": "mcp_server_policy"}})
    record_tool_dispatch("repository_search", context, None)
    # An approval hold is recorded by the approval row, not twice.
    record_tool_dispatch("deploy", context, {"tool_execution": {"category": "approval_required"}})
    await _flush(db)

    page = await list_decisions(db, workspace_id=project.id)
    by_gate = {item["gate"]: item for item in page["items"]}
    assert set(by_gate) == {"tool_policy", "mcp_access"}
    assert by_gate["tool_policy"]["outcome"] == "denied"
    assert by_gate["tool_policy"]["run_key"] == "req:req-o2"
    assert by_gate["tool_policy"]["who"] == admin.username
    assert by_gate["tool_policy"]["workspace_name"] == project.name
    counters = (await db.execute(select(PolicyDecisionCounter).where(
        PolicyDecisionCounter.workspace_id == project.id))).scalars().all()
    assert [(row.gate, row.action, row.count) for row in counters] == [("tool_policy", "repository_search", 1)]
    assert (await decisions_today(db))["allowed"] >= 1


@pytest.mark.asyncio
async def test_the_approval_lifecycle_keeps_the_request_reason_and_names_the_rule(db):
    admin = await admin_user(db)
    requester = await user_with_role(db, "operator")
    session = await session_for(db, requester)
    approval = await ensure_approval_request(db, requested_by=requester.id, action="tool:bash",
                                             reason="Run the migration script", session_id=session.id)
    await db.commit()

    decided = await resolve_approval_request(db, approval_id=approval.id, resolved_by=admin.id, status="rejected",
                                             reason="Not during the release freeze")
    await db.commit()
    await _flush(db)

    assert decided.reason == "Run the migration script"
    assert decided.decision_note == "Not during the release freeze"
    page = await list_decisions(db, approval_id=approval.id)
    lifecycle = sorted(page["items"], key=lambda item: item["time"])
    assert [item["outcome"] for item in lifecycle] == ["needs_approval", "rejected"]
    assert lifecycle[0]["reason"] == "Run the migration script"
    assert lifecycle[1]["reason"] == "Not during the release freeze"
    assert lifecycle[1]["decided_by"] == admin.username
    assert lifecycle[1]["rule"].startswith("approval rule: Four-eyes")
    detail = await get_decision(db, lifecycle[1]["id"])
    assert [item["outcome"] for item in detail["lifecycle"]] == ["needs_approval", "rejected"]


@pytest.mark.asyncio
async def test_a_gate_stopped_turn_and_a_content_policy_mask_are_records(db):
    admin = await admin_user(db)
    project = await workspace(db)
    session = await session_for(db, admin, project=project)
    await persist_turn_trace(
        db=db, session_id=session.id, message_id=None, provider="execution-gate", model="", input_messages=[],
        context_snapshot={"request_id": "req-gate-o2"}, tool_trace=[], usage={},
        raw_output=gate_outcome_marker(gate="execution_gate", label="execution gate", status="denied",
                                       reason="Workflow is not published."),
    )
    with model_call_scope(workspace_call(project.id, session_id=session.id, user_id=admin.id)):
        await RecordingProvider().chat([{"role": "user", "content": "mail jane.doe@example.org"}], "m")
    await _flush(db)

    items = (await list_decisions(db, workspace_id=project.id))["items"]
    by_gate = {item["gate"]: item for item in items}
    assert set(by_gate) == {"execution_gate", "content_security"}
    assert by_gate["execution_gate"]["run_key"] == "req:req-gate-o2"
    assert by_gate["execution_gate"]["reason"] == "Workflow is not published."
    assert by_gate["content_security"]["outcome"] == "remedied"
    assert by_gate["content_security"]["rule"] == "platform:email-masked"
    assert "jane.doe" not in str(by_gate["content_security"])
    detail = await get_decision(db, by_gate["execution_gate"]["id"])
    assert detail["run_exists"] is True


@pytest.mark.asyncio
async def test_device_dispatch_refusals_are_records(db):
    admin = await admin_user(db)
    project = await workspace(db)
    refusal = SimpleNamespace(allowed=False, state="denied", reason="folder_not_allowlisted")
    record_device_dispatch(refusal, user_id=admin.id, profile="governed", folder="/srv/app", workspace_id=project.id,
                           session_id=None)
    await _flush(db)
    items = (await list_decisions(db, gate="device_job"))["items"]
    assert items[0]["rule"] == "device policy: folder_not_allowlisted" and items[0]["outcome"] == "denied"


@pytest.mark.asyncio
async def test_decisions_api_is_admin_only(client, db):
    admin = await admin_user(db)
    viewer = await user_with_role(db, "viewer")
    for path in ("/api/v1/observability/decisions", "/api/v1/observability/decisions/today",
                 "/api/v1/observability/decisions/policy-counts"):
        assert (await call_as(client, "GET", path, viewer)).status_code == 403
        assert (await call_as(client, "GET", path, admin)).status_code == 200
    missing = await call_as(client, "GET", f"/api/v1/observability/decisions/{uuid.uuid4()}", admin)
    assert missing.status_code == 404
