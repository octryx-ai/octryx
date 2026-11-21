"""The spawn_sub_agent chat flow creates nested subthreads and tracks failed children."""

import asyncio
import json
import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import (
    AgentEvent,
)
from app.models import Session, SubAgentGroup, ToolCall
from tests.conftest import ADMIN_PASSWORD


def _spawn_response_queue():
    return [
        {
            "content": "",
            "tool_calls": [
                {
                    "id": "call-spawn",
                    "function": {
                        "name": "spawn_sub_agent",
                        "arguments": json.dumps(
                            {
                                "sub_tasks": [
                                    "Inspect service alpha",
                                    "Inspect service beta",
                                ]
                            }
                        ),
                    },
                }
            ],
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
        },
        {
            "content": "Parent completed sub-agent orchestration.",
            "tool_calls": None,
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 18, "completion_tokens": 6, "total_tokens": 24},
        },
    ]


def _stub_spawn_runtime(monkeypatch, response_queue, observed_child_runs):
    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return response_queue.pop(0), runtimes[0]

    async def fake_sub_run_agent(
        *,
        session_id,
        user_message,
        user_id,
        project_id,
        db,
        agent_type,
        runtime_target_id=None,
        thinking_level=None,
        agent_definition=None,
        parent_session_id=None,
        sub_agent_depth=0,
        run_origin=None,
    ):
        observed_child_runs.append(
            {
                "session_id": session_id,
                "user_message": user_message,
                "parent_session_id": parent_session_id,
                "sub_agent_depth": sub_agent_depth,
            }
        )
        if user_message.endswith("beta"):
            raise RuntimeError("synthetic child failure")
        db.add(
            ToolCall(
                id=str(uuid.uuid4()),
                session_id=session_id,
                tool_name="web_search",
                parameters={"query": user_message},
                result={"results": [{"url": "https://example.com/source", "title": user_message}]},
                status="success",
            )
        )
        await db.commit()
        yield AgentEvent(role="assistant", content=f"Child result for {user_message}")

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)
    monkeypatch.setattr(engine_module, "run_agent", fake_sub_run_agent)


async def _poll_until_parent_idle(client, parent_session_id, payload):
    final_payload = payload
    for _ in range(20):
        await asyncio.sleep(0.05)
        final_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={parent_session_id}")
        assert final_resp.status_code == 200
        final_payload = final_resp.json()
        if not final_payload["selectedSessionIsRunning"]:
            break
    return final_payload


async def _load_child_sessions(db, parent_session_id):
    return (
        (
            await db.execute(
                select(Session).where(Session.parent_session_id == parent_session_id).order_by(Session.started_at.asc())
            )
        )
        .scalars()
        .all()
    )


async def _load_latest_group(db, parent_session_id):
    return (
        (
            await db.execute(
                select(SubAgentGroup)
                .where(SubAgentGroup.parent_session_id == parent_session_id)
                .order_by(SubAgentGroup.created_at.desc())
            )
        )
        .scalars()
        .first()
    )


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_chat_spawn_sub_agent_flow_creates_nested_subthreads_and_tracks_failed_children(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    response_queue = _spawn_response_queue()
    observed_child_runs = []
    _stub_spawn_runtime(monkeypatch, response_queue, observed_child_runs)

    send_resp = await client.post(
        "/admin/chat/api/send",
        json={"prompt": "Fan out the work to sub-agents."},
    )
    assert send_resp.status_code == 200
    payload = send_resp.json()
    parent_session_id = payload["selectedSession"]["id"]

    final_payload = await _poll_until_parent_idle(client, parent_session_id, payload)

    assert final_payload["selectedSessionIsRunning"] is False
    assistant_contents = [
        (message["content"] or "")
        for message in final_payload["selectedMessages"]
        if message["role"] == "assistant" and (message["content"] or "").strip()
    ]
    assert assistant_contents[-1] == "Parent completed sub-agent orchestration."
    assert len(observed_child_runs) == 2
    assert all(item["parent_session_id"] == parent_session_id for item in observed_child_runs)
    assert all(item["sub_agent_depth"] == 1 for item in observed_child_runs)

    await db.rollback()
    child_sessions = await _load_child_sessions(db, parent_session_id)
    assert len(child_sessions) == 2
    assert {session.sub_agent_depth for session in child_sessions} == {1}
    failed_children = [session for session in child_sessions if session.status == "error"]
    assert len(failed_children) == 1
    assert (failed_children[0].metadata_ or {}).get("error") == "sub_agent_child_failed error_type=RuntimeError"

    spawned_group = await _load_latest_group(db, parent_session_id)
    assert spawned_group is not None
    group = spawned_group
    assert group is not None
    assert group.total_count == 2
    assert group.completed_count == 1
    assert group.failed_count == 1

    group = next(
        group
        for group in final_payload["activeThreadGroups"]
        if any(session["id"] == parent_session_id for session in group["sessions"])
    )
    parent_row = next(session for session in group["sessions"] if session["id"] == parent_session_id)
    assert parent_row["subThreadCount"] == 2
    assert {child["id"] for child in parent_row["subThreads"]} == {session.id for session in child_sessions}
    assert any(child["status"] == "error" for child in parent_row["subThreads"])
