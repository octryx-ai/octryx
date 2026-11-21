"""Chat bootstrap carries the session's approvals, the approval web API uses cookie auth with the standard error contract, and the admin panel reads and updates the exec policy."""

import json
import uuid

import pytest
from sqlalchemy import select

from app.models import Approval, ChangePreview, Session, User
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_chat_bootstrap_includes_selected_session_approvals(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        status="pending_approval",
        metadata_={"title": "Approval test thread"},
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

    bootstrap_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session.id}")
    assert bootstrap_resp.status_code == 200
    payload = bootstrap_resp.json()
    assert payload["selectedSession"]["id"] == session.id
    assert payload["selectedSession"]["status"] == "pending_approval"
    assert payload["selectedSession"]["pendingApprovalCount"] == 1
    assert len(payload["selectedApprovals"]) == 1
    assert payload["selectedApprovals"][0]["id"] == approval.id
    assert payload["selectedApprovals"][0]["action"] == "Approve command execution for bash"
    assert payload["selectedApprovals"][0]["status"] == "pending"
    assert payload["selectedApprovals"][0]["changePreview"]["preview"]["title"] == "Terraform apply"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_chat_approval_web_api_uses_cookie_auth_and_returns_chat_state(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        status="pending_approval",
        metadata_={"title": "Cookie approval thread"},
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
    await db.commit()

    approve_resp = await client.post(f"/admin/chat/api/approvals/{approval.id}/approve")
    assert approve_resp.status_code == 200
    payload = approve_resp.json()
    assert payload["selectedSession"]["id"] == session.id
    assert payload["selectedSession"]["status"] == "active"
    assert payload["selectedApprovals"][0]["status"] == "approved"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_chat_approval_web_api_missing_approval_returns_standard_error_contract(client):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    resp = await client.post(f"/admin/chat/api/approvals/{uuid.uuid4()}/approve")

    assert resp.status_code == 404
    payload = resp.json()
    assert payload["error"] == "Approval not found"
    assert payload["detail"] == "Approval not found"
    assert payload["status_code"] == 404
    assert payload["request_id"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_admin_panel_exec_policy_can_be_read_and_updated(client):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    get_resp = await client.get("/admin/chat/api/panel/exec-policy")
    assert get_resp.status_code == 200
    payload = get_resp.json()
    assert "diagnosis_read_only_commands" in payload

    payload["diagnosis_read_only_commands"] = ["python3", "git", "ls"]
    put_resp = await client.put(
        "/admin/chat/api/panel/exec-policy",
        json=payload,
    )
    assert put_resp.status_code == 200
    updated = put_resp.json()
    assert updated["diagnosis_read_only_commands"] == ["python3", "git", "ls"]

    get_again = await client.get("/admin/chat/api/panel/exec-policy")
    assert get_again.status_code == 200
    assert get_again.json()["diagnosis_read_only_commands"] == ["python3", "git", "ls"]
