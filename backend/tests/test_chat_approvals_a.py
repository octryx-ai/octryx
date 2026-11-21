"""Tests for approval API, chat send with approval, exec policy CRUD, and approval list."""

import asyncio
import json
import uuid

import pytest
from sqlalchemy import select

from app.agent.engine import (
    AgentEvent,
)
from app.models import (
    Approval,
    ChangePreview,
    Message,
    Session,
    User,
)
from app.services.approval import ensure_approval_request
from app.services.session import turn_runner
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
async def test_the_run_modes_are_listed_read_only(client):
    """A4: run modes are shipped code; the admin API lists them and cannot create or edit them."""
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303
    listed = await client.get("/admin/chat/api/panel/modes")
    assert listed.status_code == 200
    assert {mode["key"] for mode in listed.json()} >= {"diagnosis", "change", "coding"}
    assert (await client.post("/admin/chat/api/panel/modes", json={"key": "x", "name": "X"})).status_code == 405


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_approval_api_resolves_session_bound_approval_and_reactivates_session(client, db, auth_headers):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        status="pending_approval",
        metadata_={},
    )
    approval = Approval(
        id=str(uuid.uuid4()),
        task_run_id=None,
        session_id=session.id,
        requested_by=admin.id,
        action="Approve command execution for bash",
        status="pending",
        reason="Diagnosis mode requires approval\nCommand: python3 manage.py migrate",
    )
    db.add(session)
    db.add(approval)
    db.add(
        ChangePreview(
            id=str(uuid.uuid4()),
            session_id=session.id,
            approval_id=approval.id,
            tool_name="bash",
            request_fingerprint="preview-fingerprint",
            preview_json=json.dumps(
                {
                    "title": "Terraform apply",
                    "summary": "terraform apply -auto-approve",
                    "command": "terraform apply -auto-approve",
                }
            ),
        )
    )
    await db.commit()

    approve_resp = await client.post(
        f"/api/v1/approvals/{approval.id}/approve",
        json={"reason": "Approved for investigation"},
        headers=auth_headers,
    )
    assert approve_resp.status_code == 200
    payload = approve_resp.json()
    assert payload["session_id"] == session.id
    assert payload["status"] == "approved"

    await db.refresh(session)
    await db.refresh(approval)
    assert session.status == "active"
    assert approval.status == "approved"


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_chat_send_api_preserves_pending_approval_and_exposes_session_approval(
    client, db, auth_headers, monkeypatch
):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    async def fake_run_agent(*, session_id, user_message, user_id, project_id, agent_type, db, **kwargs):
        approval = await ensure_approval_request(
            db,
            requested_by=user_id,
            session_id=session_id,
            action="Approve command execution for bash",
            reason="Diagnosis mode requires approval\nCommand: python3 manage.py migrate",
        )
        db.add(
            Message(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="assistant",
                content=f"Approval required for command execution. Approval ID: {approval.id}",
            )
        )
        await db.flush()
        yield AgentEvent(
            role="assistant",
            content=f"Approval required for command execution. Approval ID: {approval.id}",
        )

    monkeypatch.setattr(turn_runner, "run_agent", fake_run_agent)

    send_resp = await client.post(
        "/admin/chat/api/send",
        json={
            "prompt": "Run python3 manage.py migrate",
        },
    )
    assert send_resp.status_code == 200, send_resp.text
    initial_payload = send_resp.json()
    session_id = initial_payload["selectedSession"]["id"]
    assert initial_payload["selectedSession"]["id"] == session_id

    final_payload = initial_payload
    for _ in range(20):
        await asyncio.sleep(0.05)
        final_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session_id}")
        assert final_resp.status_code == 200
        final_payload = final_resp.json()
        if not final_payload["selectedSessionIsRunning"]:
            break

    assert final_payload["selectedSessionIsRunning"] is False
    assert final_payload["selectedSession"]["status"] == "pending_approval"
    assert final_payload["selectedSession"]["runStatus"] == "awaiting_approval"
    assert final_payload["selectedSession"]["runCompletionReason"] == "approval_required"
    assert "Approval required" in (final_payload["selectedMessages"][-1]["content"] or "")

    approvals_resp = await client.get("/api/v1/approvals", headers=auth_headers)
    assert approvals_resp.status_code == 200
    approvals = approvals_resp.json()
    matching = [item for item in approvals if item["session_id"] == session_id]
    assert len(matching) == 1
    assert matching[0]["status"] == "pending"
    assert matching[0]["task_run_id"] is None
    assert final_payload["selectedSession"]["pendingApprovalCount"] == 1
    assert len(final_payload["selectedApprovals"]) == 1
    assert final_payload["selectedApprovals"][0]["status"] == "pending"
    assert final_payload["selectedApprovals"][0]["sessionId"] == session_id
