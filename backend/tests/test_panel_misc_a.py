"""Tests for bitbucket commit report, tool call artifacts, bootstrap thread number, and agent builder templates."""

import uuid

import pytest
from sqlalchemy import select

from app.agent.engine import (
    _format_recent_bitbucket_commits_report,
)
from app.models import ChannelConfig, Project, Session, Task, TaskRun, ToolCall, User
from app.scheduler.output.channel_output import deliver_task_output_channel
from app.web import _context as web_context
from app.web._helpers.tool_call_serialization import _serialize_tool_call
from tests.conftest import ADMIN_PASSWORD


def test_recent_bitbucket_commit_report_renders_markdown_table():
    content = _format_recent_bitbucket_commits_report(
        {
            "days": 5,
            "commits": [
                {
                    "project_key": "SHOP",
                    "repo_slug": "acme-orders-config",
                    "repository_label": "SHOP/acme-orders-config",
                    "display_id": "0b07e35bf23",
                    "author_name": "Alice Example",
                    "author_timestamp": 1_710_000_000_000,
                    "message": "Merge branch feature/ACME-390 into main",
                }
            ],
        }
    )

    assert "Here is the table of all commits from the last 5 days" in content
    assert "| Repository | Date | Commit | Author | Message |" in content
    assert "SHOP/acme-orders-config" in content
    assert "0b07e35bf23" in content


def test_serialize_tool_call_infers_artifact_from_stdout(tmp_path, monkeypatch):
    artifact = tmp_path / "commits_by_author.png"
    artifact.write_bytes(b"fake-png-data")
    monkeypatch.setattr(web_context, "WORKSPACE_ROOT", tmp_path)

    tool_call = ToolCall(
        id=str(uuid.uuid4()),
        session_id="session",
        message_id="message",
        tool_name="run_saved_python_script",
        parameters={"name": "bitbucket_commits_visualization"},
        result={"stdout": f"Chart saved as: {artifact.name}\n", "exit_code": 0},
        status="success",
        duration_ms=120,
    )

    payload = _serialize_tool_call(tool_call)
    assert len(payload["artifacts"]) == 1
    assert payload["artifacts"][0]["name"] == "commits_by_author.png"
    assert payload["artifacts"][0]["mediaType"] == "image/png"
    assert "chat/api/artifact" in payload["artifacts"][0]["url"]


def test_serialize_tool_call_exposes_execution_events():
    event = {
        "kind": "test",
        "tool_name": "run_test_suite",
        "cwd": "/workspace/repo",
        "status": "failed",
        "exit_code": 1,
        "duration_ms": 140,
        "stdout_chars": 10,
        "stderr_chars": 0,
        "stdout_truncated": False,
        "stderr_truncated": False,
    }
    tool_call = ToolCall(
        id=str(uuid.uuid4()),
        session_id="session",
        message_id="message",
        tool_name="run_test_suite",
        parameters={},
        result={"execution_event": event, "execution_events": [{"status": "started"}, event]},
        status="error",
        duration_ms=140,
    )

    payload = _serialize_tool_call(tool_call)

    assert payload["executionEvent"] == event
    assert payload["executionEvents"] == [{"status": "started"}, event]


def test_serialize_tool_call_exposes_execution_event_from_externalized_preview():
    event = {
        "kind": "patch",
        "tool_name": "apply_patch_workspace",
        "cwd": "/workspace/repo",
        "status": "succeeded",
        "exit_code": 0,
        "duration_ms": 20,
        "stdout_chars": 0,
        "stderr_chars": 0,
        "stdout_truncated": False,
        "stderr_truncated": False,
    }
    tool_call = ToolCall(
        id=str(uuid.uuid4()),
        session_id="session",
        message_id="message",
        tool_name="apply_patch_workspace",
        parameters={},
        result={"preview": {"compact_result": {"execution_event": event}}},
        status="success",
        duration_ms=20,
    )

    payload = _serialize_tool_call(tool_call)

    assert payload["executionEvent"] == event


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_admin_chat_bootstrap_exposes_thread_number_and_session_id(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        agent_type="chat",
        status="active",
        metadata_={"title": "Header thread"},
    )
    db.add(session)
    await db.commit()

    bootstrap_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session.id}")
    assert bootstrap_resp.status_code == 200
    payload = bootstrap_resp.json()
    assert payload["selectedSession"]["id"] == session.id
    assert payload["selectedSession"]["threadNumber"] >= 1

    active_sessions = [
        item for group in payload["activeThreadGroups"] for item in group["sessions"] if item["id"] == session.id
    ]
    assert active_sessions
    assert active_sessions[0]["threadNumber"] == payload["selectedSession"]["threadNumber"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_task_output_can_be_delivered_to_configured_channel(db, monkeypatch):
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Nightly Summary",
        description="Send result",
        task_type="agent_run",
        agent_type="chat",
        config={"output_channel_id": 1},
        is_active=True,
        owner_id=admin_user.id,
    )
    run = TaskRun(
        id=str(uuid.uuid4()),
        task_id=task.id,
        session_id="session-123",
        trigger_type="manual",
        status="success",
        started_by=admin_user.id,
        output={"response": "Summary completed", "step_count": 3},
    )
    channel = ChannelConfig(
        id=1,
        plugin_id="slack",
        name="Ops Slack",
        project_id=project.id,
        enabled=True,
        config='{"default_target":"C0123456789"}',
    )
    db.add(task)
    db.add(run)
    db.add(channel)
    await db.commit()

    sent = {}

    class FakePlugin:
        async def send_message(self, target, content, **kwargs):
            sent["target"] = target
            sent["content"] = content
            sent["kwargs"] = kwargs
            return True

    from app.plugins import plugin_manager

    monkeypatch.setattr(plugin_manager, "get_channel", lambda channel_id: FakePlugin())

    result = await deliver_task_output_channel(db, task, run)
    assert result is not None
    assert result["status"] == "sent"
    assert sent["target"] == "C0123456789"
    assert "Task run finished: Nightly Summary" in sent["content"]
    assert "/chat?session_id=session-123" in sent["content"] and "/admin/chat" not in sent["content"]
