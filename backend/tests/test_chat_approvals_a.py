"""Tests for approval API, chat send with approval, exec policy CRUD, and approval list."""

import json
import uuid

import pytest
from sqlalchemy import select

from app.models import (
    Approval,
    ChangePreview,
    Session,
    User,
)
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
async def test_the_run_modes_are_listed_read_only(client):
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


