"""The summary loader reports approvals, artifacts and runtime failures without raw content, treats traces without a snapshot as unknown, and the route is owner scoped."""

import json
import uuid

import pytest

from app.models import Approval, ToolCall, User
from app.models.runtime.artifact_store import ToolArtifact
from app.services.auth import hash_password
from app.services.session.turn_execution_summary_service import load_user_turn_execution_summary
from tests.conftest import ADMIN_PASSWORD
from tests.turn_execution_summary_api_support import SECRET, _admin, _allowed_snapshot, _session, _trace


@pytest.mark.asyncio
async def test_loader_reports_pending_approval_and_artifact_metadata_only(db):
    admin = await _admin(db)
    session = await _session(db, admin.id)
    trace = await _trace(db, session, snapshot=_allowed_snapshot())
    approval = Approval(
        id=str(uuid.uuid4()),
        session_id=session.id,
        requested_by=admin.id,
        action=f"terraform apply -var token={SECRET}",
        status="pending",
        reason=f"because {SECRET}",
    )
    db.add(approval)
    tool_call_id = str(uuid.uuid4())
    db.add(
        ToolCall(
            id=tool_call_id,
            session_id=session.id,
            message_id=trace.message_id,
            tool_name="terraform_apply",
            parameters={"token": SECRET},
            result={"approval_required": True, "approval_status": "pending", "approval_id": approval.id},
            status="success",
        )
    )
    db.add(
        ToolArtifact(
            id=tool_call_id,
            session_id=session.id,
            message_id=trace.message_id,
            tool_name="terraform_apply",
            relative_path=f"{session.id}/{tool_call_id}.json.gz",
            content_sha256="a" * 64,
            payload_size_bytes=4096,
            preview_json={"compact_result": {"secret": SECRET}},
        )
    )
    await db.flush()

    summary = await load_user_turn_execution_summary(db, user_id=admin.id, trace_id=trace.id)
    assert summary["state"] == "waiting_approval"
    assert summary["approvals"][0]["approval_id"] == approval.id
    assert summary["approvals"][0]["status"] == "pending"
    assert summary["capabilities_used"] == [{"name": "terraform_apply", "calls": 1, "succeeded": 1, "failed": 0}]
    assert summary["artifacts"][0]["artifact_id"] == tool_call_id
    assert summary["artifacts"][0]["size_bytes"] == 4096
    payload = json.dumps(summary)
    assert SECRET not in payload
    assert "relative_path" not in payload
    assert "content_sha256" not in payload


@pytest.mark.asyncio
async def test_loader_treats_foreign_session_approval_as_unknown(db):
    admin = await _admin(db)
    session = await _session(db, admin.id)
    other = await _session(db, admin.id)
    trace = await _trace(db, session, snapshot=_allowed_snapshot())
    foreign = Approval(id=str(uuid.uuid4()), session_id=other.id, requested_by=admin.id, action="x", status="approved")
    db.add(foreign)
    db.add(
        ToolCall(
            id=str(uuid.uuid4()),
            session_id=session.id,
            message_id=trace.message_id,
            tool_name="helm_upgrade",
            parameters={},
            result={"approval_required": True, "approval_status": "pending", "approval_id": foreign.id},
            status="success",
        )
    )
    await db.flush()

    summary = await load_user_turn_execution_summary(db, user_id=admin.id, trace_id=trace.id)
    assert summary["state"] == "unknown"
    assert summary["approvals"][0]["status"] == "unknown"


@pytest.mark.asyncio
async def test_loader_reports_runtime_failure_without_raw_error(db):
    admin = await _admin(db)
    session = await _session(db, admin.id)
    trace = await _trace(
        db,
        session,
        snapshot=_allowed_snapshot(),
        raw_output={"error": f"401 Unauthorized: Bearer {SECRET}", "runtime_attempts": []},
    )
    summary = await load_user_turn_execution_summary(db, user_id=admin.id, trace_id=trace.id)
    assert summary["state"] == "failed"
    assert SECRET not in json.dumps(summary)
    assert "Unauthorized" not in json.dumps(summary)


@pytest.mark.asyncio
async def test_a_trace_without_snapshot_is_unknown_even_when_session_has_a_current_profile(db):
    admin = await _admin(db)
    session = await _session(
        db,
        admin.id,
        metadata={"execution_profile": {"version": "execution_profile.v1", "status": "allowed"}},
    )
    trace = await _trace(db, session, snapshot=None)
    summary = await load_user_turn_execution_summary(db, user_id=admin.id, trace_id=trace.id)
    assert summary["state"] == "unknown"
    assert summary["state_reason"]["code"] == "missing_snapshot"
    assert summary["execution_profile"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["", "/admin"])
async def test_execution_summary_route_is_owner_scoped(client, db, prefix):
    admin = await _admin(db)
    session = await _session(db, admin.id)
    trace = await _trace(db, session, snapshot=_allowed_snapshot(finished=True))
    outsider = User(
        id=str(uuid.uuid4()),
        username=f"outsider-{uuid.uuid4().hex[:6]}",
        email=f"outsider-{uuid.uuid4().hex[:6]}@example.com",
        password_hash=hash_password("secret123"),
        display_name="Outsider",
        is_active=True,
    )
    db.add(outsider)
    await db.commit()

    url = f"{prefix}/chat/api/turn-traces/{trace.id}/execution-summary"
    unauthenticated = await client.get(url)
    assert unauthenticated.status_code == 401

    login = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login.status_code == 303
    owner_resp = await client.get(url)
    assert owner_resp.status_code == 200
    body = owner_resp.json()
    assert body["version"] == "turn_execution_summary.v1"
    assert body["trace_id"] == trace.id
    assert body["state"] == "finished_unverified"
    assert SECRET not in owner_resp.text

    unknown_resp = await client.get(f"{prefix}/chat/api/turn-traces/{uuid.uuid4()}/execution-summary")
    assert unknown_resp.status_code == 404

    client.cookies.clear()
    login = await client.post("/admin/login", data={"username": outsider.username, "password": "secret123"})
    assert login.status_code == 303
    foreign_resp = await client.get(url)
    assert foreign_resp.status_code == 404
    # Non-disclosing: a foreign trace is indistinguishable from an unknown one.
    def _without_request_id(payload: dict) -> dict:
        return {key: value for key, value in payload.items() if key != "request_id"}

    assert _without_request_id(foreign_resp.json()) == _without_request_id(unknown_resp.json())
