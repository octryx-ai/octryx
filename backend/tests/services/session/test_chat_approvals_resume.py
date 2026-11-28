"""Tests for approve/resume/reject endpoints, continuation, and approval safe followup."""

import uuid

import pytest
from sqlalchemy import select

import app.services.session.approval_decision as approval_decision_module
from app.models import Approval, Project, Session, User
from tests.chat_approvals_support import _server_pipeline  # noqa: F401


@pytest.mark.asyncio
async def test_admin_panel_exec_policy_configs_crud(admin_client, db):
    project = Project(id=str(uuid.uuid4()), name="Acme Orders")
    db.add(project)
    await db.commit()

    create_resp = await admin_client.post(
        "/admin/chat/api/panel/exec-policies",
        json={
            "name": "Acme Orders diagnosis policy",
            "projectId": project.id,
            "priority": 40,
            "isActive": True,
            "config": {
                "diagnosis_read_only_commands": ["python3", "ls"],
                "diagnosis_git_subcommands": ["status"],
                "diagnosis_kubectl_verbs": ["get"],
                "diagnosis_review_commands": ["npm"],
                "always_deny_patterns": [r"rm -rf /"],
                "shell_risk_operators": ["&&"],
            },
        },
    )
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["projectId"] == project.id
    assert created["name"] == "Acme Orders diagnosis policy"

    list_resp = await admin_client.get("/admin/chat/api/panel/exec-policies")
    assert list_resp.status_code == 200
    rows = list_resp.json()
    item = next(row for row in rows if row["id"] == created["id"])
    assert item["projectName"] == "Acme Orders"
    assert item["config"]["diagnosis_read_only_commands"] == ["python3", "ls"]
    # The retired review list (it never changed an outcome) is dropped from stored payloads.
    assert "diagnosis_review_commands" not in item["config"]

    update_resp = await admin_client.put(
        f"/admin/chat/api/panel/exec-policies/{created['id']}",
        json={
            "name": "Acme Orders stricter diagnosis policy",
            "projectId": project.id,
            "priority": 30,
            "isActive": False,
            "config": {
                "diagnosis_read_only_commands": ["python3"],
                "diagnosis_git_subcommands": ["status", "show"],
                "diagnosis_kubectl_verbs": ["get"],
                "diagnosis_review_commands": ["npm", "pip"],
                "always_deny_patterns": [r"rm -rf /"],
                "shell_risk_operators": ["&&", ";"],
            },
        },
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["name"] == "Acme Orders stricter diagnosis policy"
    assert updated["priority"] == 30
    assert updated["isActive"] is False

    delete_resp = await admin_client.delete(f"/admin/chat/api/panel/exec-policies/{created['id']}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["ok"] is True

    list_again = await admin_client.get("/admin/chat/api/panel/exec-policies")
    assert list_again.status_code == 200
    assert all(row["id"] != created["id"] for row in list_again.json())


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_the_chat_card_approve_resolves_and_resumes_session(admin_client, db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        status="pending_approval",
        metadata_={"title": "Approval thread"},
    )
    approval = Approval(
        id=str(uuid.uuid4()),
        task_run_id=None,
        session_id=session.id,
        requested_by=admin.id,
        action="Approve command execution for bash",
        status="pending",
        reason="Need approval",
    )
    db.add(session)
    db.add(approval)
    await db.commit()

    resumed = {"value": False}

    async def fake_resume_decided_approval(db, *, session, approval, decision, session_factory=None):
        resumed["value"] = decision == "approved"
        session.status = "active"
        await db.commit()

    # Every decision route resumes through the one owner (services/session/approval_decision).
    monkeypatch.setattr(approval_decision_module, "resume_decided_approval", fake_resume_decided_approval)

    # The chat card decides approvals on their owning screen.
    resp = await admin_client.post(f"/admin/chat/api/approvals/{approval.id}/approve")
    assert resp.status_code == 200
    assert resumed["value"] is True

    await db.refresh(approval)
    await db.refresh(session)
    assert approval.status == "approved"
    assert session.status == "active"
