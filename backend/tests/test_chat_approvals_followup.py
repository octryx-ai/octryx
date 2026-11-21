"""Approval resume continues the agent turn for change-preview grants and a rejection resumes with a safe follow-up."""

import asyncio
import json
import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.agent.engine import (
    AgentEvent,
)
from app.models import Approval, ChangePreview, Message, Session, User
from app.services.session import turn_runner
from app.services.session.turn_approval_state import end_chat_turn, hold_turn_for_approval
from tests.chat_approvals_support import _server_pipeline  # noqa: F401
from tests.conftest import ADMIN_PASSWORD


def _pause_turn_at(session: Session, approval: Approval) -> None:
    """The state a real turn leaves behind: the approval bound to its turn, the turn marker cleared."""
    hold_turn_for_approval(session, approval_id=approval.id, requested_by=approval.requested_by)
    metadata = dict(session.metadata_ or {})
    end_chat_turn(metadata)
    session.metadata_ = metadata


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_chat_approval_resume_continues_agent_turn_for_change_preview_grants(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        status="pending_approval",
        metadata_={"title": "Resume preview approval thread"},
    )
    user_message = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="user",
        content="Prüfe die geplante Änderung und fahre dann fort",
    )
    assistant_message = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="assistant",
        content="Approval required.",
    )
    session.metadata_["current_turn_user_message_id"] = user_message.id
    approval = Approval(
        id=str(uuid.uuid4()),
        task_run_id=None,
        session_id=session.id,
        requested_by=admin.id,
        action="Approve command execution for bash",
        status="pending",
        reason="Diagnosis mode requires approval",
    )
    _pause_turn_at(session, approval)
    preview = ChangePreview(
        id=str(uuid.uuid4()),
        session_id=session.id,
        approval_id=approval.id,
        tool_name="bash",
        request_fingerprint="resume-preview-grant",
        preview_json=json.dumps({"summary": "preview grant"}),
    )
    db.add_all([session, user_message, assistant_message, approval, preview])
    await db.commit()

    async def fake_run_agent(*, session_id, user_message, db, **kwargs):
        assert session_id == session.id
        assert user_message == "Prüfe die geplante Änderung und fahre dann fort"
        db.add(
            Message(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="assistant",
                content="Preview approval resumed turn.",
            )
        )
        await db.flush()
        yield AgentEvent(role="assistant", content="Preview approval resumed turn.")

    monkeypatch.setattr(turn_runner, "run_agent", fake_run_agent)

    approve_resp = await client.post(f"/admin/chat/api/approvals/{approval.id}/approve")
    assert approve_resp.status_code == 200

    final_payload = approve_resp.json()
    for _ in range(20):
        await asyncio.sleep(0.05)
        final_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session.id}")
        assert final_resp.status_code == 200
        final_payload = final_resp.json()
        if not final_payload["selectedSessionIsRunning"]:
            break

    assistant_contents = [
        (message["content"] or "") for message in final_payload["selectedMessages"] if message["role"] == "assistant"
    ]
    assert "Preview approval resumed turn." in assistant_contents[-1]
    assert final_payload["selectedSession"]["runStatus"] == "completed"


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_chat_reject_approval_resumes_with_safe_followup(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        status="pending_approval",
        metadata_={"title": "Reject approval thread"},
    )
    user_message = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="user",
        content="Führe einen riskanten Befehl aus",
    )
    assistant_message = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="assistant",
        content="Approval required.",
    )
    session.metadata_["current_turn_user_message_id"] = user_message.id
    approval = Approval(
        id=str(uuid.uuid4()),
        task_run_id=None,
        session_id=session.id,
        requested_by=admin.id,
        action="Approve command execution for bash",
        status="pending",
        reason="Needs approval before risky command",
    )
    _pause_turn_at(session, approval)
    db.add_all([session, user_message, assistant_message, approval])
    await db.commit()

    captured: dict[str, Any] = {}

    async def fake_run_agent(*, session_id, user_message, db, **kwargs):
        assert session_id == session.id
        captured["user_message"] = user_message
        db.add(
            Message(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="assistant",
                content="Approval was rejected. I can continue with a safe read-only check instead.",
            )
        )
        await db.flush()
        yield AgentEvent(
            role="assistant",
            content="Approval was rejected. I can continue with a safe read-only check instead.",
        )

    monkeypatch.setattr(turn_runner, "run_agent", fake_run_agent)

    reject_resp = await client.post(f"/admin/chat/api/approvals/{approval.id}/reject")
    assert reject_resp.status_code == 200

    final_payload = reject_resp.json()
    for _ in range(20):
        await asyncio.sleep(0.05)
        final_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session.id}")
        assert final_resp.status_code == 200
        final_payload = final_resp.json()
        if not final_payload["selectedSessionIsRunning"]:
            break

    assert "approval was rejected" in captured["user_message"].lower()
    assert "Do not attempt the rejected action".lower() in captured["user_message"].lower()
    assistant_contents = [
        (message["content"] or "") for message in final_payload["selectedMessages"] if message["role"] == "assistant"
    ]
    assert "safe read-only check" in assistant_contents[-1].lower()
    assert final_payload["selectedSession"]["runStatus"] == "completed"
    assert final_payload["selectedApprovals"][0]["status"] == "rejected"
