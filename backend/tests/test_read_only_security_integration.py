"""An enforced read-only run never runs a granted mutating command: every read-only refusal is final before
any grant, standing rule or approval request, proven on the real turn, tool and approval paths."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Approval, Message, Project, User
from app.models import Session as AgentSession
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from tests.conftest import ADMIN_PASSWORD
from tests.shell_expansion_support import _granted_session, _runtime, exec_config  # noqa: F401

pytestmark = pytest.mark.asyncio
WRITES = ["sort -o out input", "python3 manage.py migrate", "git commit -am x", "uniq in out"]


def _phase_resolution(capability_class: str) -> dict:
    return {"source": "db", "status": "matched", "selection_source": "workflow_run", "workflow_key": "probe",
            "workflow_id": "probe", "policy_id": "p", "policy_version_id": "v",
            "workflow_contract": {"workflow_id": "probe", "capability_class": capability_class}}




async def _state(db, resolution: dict | None) -> dict:
    from app.services.run_capability.resolution import resolve_run_capability

    metadata = {ROUTING_RESOLUTION_KEY: resolution} if resolution else {}
    capability = await resolve_run_capability(db, session_metadata=metadata, routing_resolution=resolution,
                                              requested_agent_type="chat", agent_definition=None,
                                              parent_session_id=None)
    return capability.tool_context_state()


CONTEXTS = {"assistant outside a run": None, "read_only phase": _phase_resolution("read_only")}








async def test_approving_a_mutating_command_in_a_read_only_chat_does_not_run_it(client, db, monkeypatch):
    assert (await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
            ).status_code == 303
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=str(uuid.uuid4()), name="Read-only chat", config={}, is_active=True)
    db.add(project)
    await db.flush()
    session = AgentSession(id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, agent_type="chat",
                           status="pending_approval", metadata_={"title": "Old approval"})
    message = Message(id=str(uuid.uuid4()), session_id=session.id, role="user", content="Run the migration")
    session.metadata_["current_turn_user_message_id"] = message.id
    approval = Approval(id=str(uuid.uuid4()), task_run_id=None, session_id=session.id, requested_by=admin.id,
                        action="Approve command execution for bash", status="pending",
                        reason="Diagnosis mode requires approval\nCommand: python3 manage.py migrate")
    db.add_all([session, message, approval])
    await db.commit()
    ran = []

    async def fake_shell(command, **kwargs):
        ran.append(command)
        raise AssertionError("a read-only chat never runs an approved write")

    monkeypatch.setattr("asyncio.create_subprocess_shell", fake_shell)
    approved = await client.post(f"/admin/chat/api/approvals/{approval.id}/approve")
    assert approved.status_code == 200 and ran == []
