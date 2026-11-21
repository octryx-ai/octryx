"""The chat send API recovers from a transitional response, and the parent thread bootstrap exposes a subthread's pending approval."""

import asyncio
import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.models import Approval, Project, Session, User
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_chat_send_api_recovers_from_transitional_response_and_finishes(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    project_id = project.id
    response_queue = [
        {
            "content": (
                "The report-builder component is not directly visible in the available repositories. Let me search for "
                "report-builder in the Confluence Knowledge Map and for references in the repositories:"
            ),
            "tool_calls": None,
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
        },
        {
            "content": "",
            "tool_calls": [
                {
                    "id": "call-knowledge",
                    "function": {
                        "name": "list_project_knowledge",
                        "arguments": '{"query": "report-builder", "limit": 5}',
                    },
                }
            ],
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 12, "completion_tokens": 2, "total_tokens": 14},
        },
        {
            "content": (
                "Report Builder builds weekly order reports from the shop's "
                "exports and documents the report schedule and checks."
            ),
            "tool_calls": None,
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 18, "completion_tokens": 6, "total_tokens": 24},
        },
    ]
    executed_tools: list[str] = []

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return response_queue.pop(0), runtimes[0]

    async def fake_execute_tool_with_plugins(tool_name, tool_args, tool_context):
        executed_tools.append(tool_name)
        return {
            "project_name": "acme-orders",
            "results": [
                {
                    "title": "Report Builder",
                    "summary": "Weekly report schedule with validation checks.",
                }
            ],
        }

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)
    monkeypatch.setattr(engine_module, "execute_tool_with_plugins", fake_execute_tool_with_plugins)

    send_resp = await client.post(
        "/admin/chat/api/send",
        json={
            "prompt": "What can you tell me about the report-builder?",
            "project_id": project_id,
        },
    )
    assert send_resp.status_code == 200
    payload = send_resp.json()
    session_id = payload["selectedSession"]["id"]

    final_payload = payload
    for _ in range(100):
        await asyncio.sleep(0.05)
        final_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session_id}")
        assert final_resp.status_code == 200
        final_payload = final_resp.json()
        if not final_payload["selectedSessionIsRunning"]:
            break

    assert final_payload["selectedSessionIsRunning"] is False
    assert executed_tools == ["list_project_knowledge"]
    assistant_contents = [
        item["content"] or "" for item in final_payload["selectedMessages"] if item["role"] == "assistant"
    ]
    assert assistant_contents[-1].startswith("Report Builder builds weekly order reports")
    assert not any("Let me search for report-builder" in content for content in assistant_contents)


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_chat_bootstrap_parent_thread_exposes_subthread_pending_approval_state(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="change",
        status="active",
        metadata_={"title": "Parent builder"},
    )
    child_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="diagnosis",
        status="pending_approval",
        metadata_={"title": "Child approval"},
        parent_session_id=parent_session.id,
        sub_agent_depth=1,
    )
    approval = Approval(
        id=str(uuid.uuid4()),
        task_run_id=None,
        session_id=child_session.id,
        requested_by=admin_user.id,
        action="Approve command execution for bash",
        status="pending",
        reason="Diagnosis mode requires approval\nCommand: python3 manage.py migrate",
    )
    db.add(parent_session)
    db.add(child_session)
    db.add(approval)
    await db.commit()

    bootstrap_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={parent_session.id}")
    assert bootstrap_resp.status_code == 200
    payload = bootstrap_resp.json()

    group = next(group for group in payload["activeThreadGroups"] if group["projectName"] == "acme-orders")
    parent_row = next(session for session in group["sessions"] if session["id"] == parent_session.id)
    assert parent_row["subThreadCount"] == 1
    assert parent_row["subThreads"][0]["id"] == child_session.id
    assert parent_row["subThreads"][0]["status"] == "pending_approval"
    assert parent_row["subThreads"][0]["pendingApprovalCount"] == 1
