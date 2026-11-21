"""Runtime regression pack: context pressure is retried with trimmed messages, a stale prefetch never beats the session cache, and large tool results are compacted while the full artifact stays loadable."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.agent.core.turn.tool_call_recording import WORKING_SET_COMPACT_RESULT_TOKEN_BUDGET
from app.agent.core.turn.turn_diff import TurnDiffTracker
from app.agent.core.turn.turn_tools import execute_tool_call_for_turn
from app.agent.engine import _chat_with_runtime_fallback
from app.models import Message, PrefetchCacheEntry, Session, SessionToolCacheEntry, ToolCall, User
from app.services.prefetch import build_prefetch_params_hash
from app.services.session.tool_cache import build_session_tool_cache_hash
from app.services.tool_artifact import load_tool_artifact_payload, parse_tool_artifact_envelope
from app.services.tool_result_compression.support import _estimate_tokens
from app.time_utils import utc_now
from app.tools.context import ToolContext


def _assistant_tool_call_ids(messages: list[dict[str, Any]]) -> set[str]:
    return {
        str(tool_call.get("id") or "").strip()
        for message in messages
        if message.get("role") == "assistant"
        for tool_call in list(message.get("tool_calls") or [])
        if str(tool_call.get("id") or "").strip()
    }


def _tool_result_ids(messages: list[dict[str, Any]]) -> set[str]:
    return {
        str(message.get("tool_call_id") or "").strip()
        for message in messages
        if message.get("role") == "tool" and str(message.get("tool_call_id") or "").strip()
    }


async def _create_session_with_assistant_message(db) -> tuple[User, str, str]:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session_id = str(uuid.uuid4())
    assistant_message_id = str(uuid.uuid4())
    db.add(Session(id=session_id, user_id=admin.id, metadata_={}))
    db.add(Message(id=assistant_message_id, session_id=session_id, role="assistant", content="tool"))
    await db.commit()
    return admin, session_id, assistant_message_id


@pytest.mark.asyncio
async def test_runtime_regression_pack_retries_context_pressure_with_trimmed_messages(monkeypatch):
    captured_attempts: list[dict[str, Any]] = []

    class RetryProvider:
        async def chat(self, **kwargs):
            captured_attempts.append(
                {
                    "messages": [dict(message) for message in kwargs["messages"]],
                    "max_tokens": kwargs["max_tokens"],
                }
            )
            if len(captured_attempts) == 1:
                raise RuntimeError("context window exceeded")
            return {"content": "ok", "tool_calls": [], "usage": {}, "model": kwargs["model"]}

        async def close(self):
            return None

    monkeypatch.setattr("app.agent.engine.get_provider", lambda **kwargs: RetryProvider())

    messages = [
        {"role": "system", "content": "system " * 1200},
        {"role": "user", "content": "old request " * 400},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call-old-a", "function": {"name": "todo_read", "arguments": "{}"}},
                {"id": "call-old-b", "function": {"name": "todo_read", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call-old-a", "content": "artifact-a " * 500},
        {"role": "tool", "tool_call_id": "call-old-b", "content": "artifact-b " * 500},
        {"role": "assistant", "content": "older narrative " * 500},
        {"role": "user", "content": "current request"},
    ]

    response, runtime, runtime_attempts = await _chat_with_runtime_fallback(
        [
            {
                "provider_name": "copilot",
                "api_key": "test",
                "model": "claude-haiku-4.5",
                "target_id": "ctx",
                "max_context_retries": 1,
            }
        ],
        messages=messages,
        tools=None,
        max_tokens=800,
        request_timeout_seconds=5,
    )

    first_attempt = captured_attempts[0]
    second_attempt = captured_attempts[1]

    assert response["content"] == "ok"
    assert runtime["target_id"] == "ctx"
    assert runtime_attempts[0]["error_class"] == "context_pressure"
    assert runtime_attempts[0]["retry_decision"] == "same_runtime_retry"
    assert second_attempt["max_tokens"] == 600
    assert second_attempt["messages"][-1] == {"role": "user", "content": "current request"}
    assert len(json.dumps(second_attempt["messages"])) < len(json.dumps(first_attempt["messages"]))
    assert "call-old-a" not in _tool_result_ids(second_attempt["messages"])
    assert "call-old-b" not in _tool_result_ids(second_attempt["messages"])
    assert _assistant_tool_call_ids(second_attempt["messages"]) == _tool_result_ids(second_attempt["messages"])


@pytest.mark.asyncio
async def test_runtime_regression_pack_ignores_stale_prefetch_before_using_session_cache(db):
    admin, session_id, assistant_message_id = await _create_session_with_assistant_message(db)

    params = {"namespace": "prod"}
    db.add(
        PrefetchCacheEntry(
            session_id=session_id,
            tool_name="list_failed_pods",
            params_hash=build_prefetch_params_hash("list_failed_pods", params),
            params_json=params,
            result_json={"source": "prefetch", "failed_count": 1},
            status="completed",
            completed_at=utc_now() - timedelta(minutes=10),
        )
    )
    db.add(
        SessionToolCacheEntry(
            id=str(uuid.uuid4()),
            session_id=session_id,
            tool_name="list_failed_pods",
            params_hash=build_session_tool_cache_hash("list_failed_pods", params),
            result_json={"source": "session", "failed_count": 2},
            ttl_seconds=60,
            cached_at=utc_now(),
        )
    )
    await db.commit()

    execution_count = {"count": 0}

    async def fake_execute_tool(tool_name, tool_args, tool_context):
        execution_count["count"] += 1
        return {"source": "live"}

    executed = await execute_tool_call_for_turn(
        db=db,
        assistant_message_id=assistant_message_id,
        tool_call={
            "id": "stale-prefetch",
            "function": {"name": "list_failed_pods", "arguments": json.dumps(params)},
        },
        tool_context=ToolContext(
            user_id=admin.id,
            project_ids=[],
            roles=["admin"],
            session_id=session_id,
            project_config={},
            db=db,
            workspace_root=str(Path.cwd()),
        ),
        active_steps=[],
        current_step_index=0,
        current_step_tool_activity=False,
        current_allowed_tool_names=set(),
        latest_repo_state={},
        infer_repo_tool_args=lambda tool_name, tool_args, latest_repo_state: tool_args,
        resolve_allowed_tools_for_step_tool_call=lambda **kwargs: (
            kwargs["current_step_index"],
            kwargs["current_step_tool_activity"],
            kwargs["current_allowed_tool_names"],
        ),
        compact_tool_result_for_model=lambda tool_name, result: result,
        summary_domains_satisfied_by_result=lambda tool_name, result: set(),
        execute_tool=fake_execute_tool,
        turn_diff_tracker=TurnDiffTracker(),
        context_snapshot={},
    )

    assert executed.tool_result["result"]["source"] == "session"
    assert executed.tool_result["cache"]["status"] == "hit"
    assert execution_count["count"] == 0


@pytest.mark.asyncio
async def test_runtime_regression_pack_compacts_large_tool_results_and_keeps_full_artifact_loadable(db):
    admin, session_id, assistant_message_id = await _create_session_with_assistant_message(db)

    huge_result = {
        "content": "x" * 50000,
        "items": [{"index": index, "value": "y" * 3000} for index in range(80)],
    }

    async def fake_execute_tool(tool_name, tool_args, tool_context):
        return huge_result

    executed = await execute_tool_call_for_turn(
        db=db,
        assistant_message_id=assistant_message_id,
        tool_call={
            "id": "large-result",
            "function": {"name": "todo_read", "arguments": json.dumps({})},
        },
        tool_context=ToolContext(
            user_id=admin.id,
            project_ids=[],
            roles=["admin"],
            session_id=session_id,
            project_config={},
            db=db,
            workspace_root=str(Path.cwd()),
        ),
        active_steps=[],
        current_step_index=0,
        current_step_tool_activity=False,
        current_allowed_tool_names=set(),
        latest_repo_state={},
        infer_repo_tool_args=lambda tool_name, tool_args, latest_repo_state: tool_args,
        resolve_allowed_tools_for_step_tool_call=lambda **kwargs: (
            kwargs["current_step_index"],
            kwargs["current_step_tool_activity"],
            kwargs["current_allowed_tool_names"],
        ),
        compact_tool_result_for_model=lambda tool_name, result: result,
        summary_domains_satisfied_by_result=lambda tool_name, result: set(),
        execute_tool=fake_execute_tool,
        turn_diff_tracker=TurnDiffTracker(),
        context_snapshot={},
    )
    await db.flush()

    envelope = parse_tool_artifact_envelope(executed.message_for_model["content"])
    tool_call_row = await db.get(ToolCall, executed.tool_result["artifact_id"])
    loaded_payload = await load_tool_artifact_payload(
        db,
        session_id=session_id,
        artifact_id=executed.tool_result["artifact_id"],
        detail_level="full",
    )

    assert executed.tool_result["compact_result"]["_hard_capped"] is True
    assert _estimate_tokens(executed.tool_result["compact_result"]) <= WORKING_SET_COMPACT_RESULT_TOKEN_BUDGET
    assert envelope is not None
    assert envelope["result"]["_hard_capped"] is True
    assert _estimate_tokens(envelope["result"]) <= WORKING_SET_COMPACT_RESULT_TOKEN_BUDGET
    assert isinstance(tool_call_row.result, dict)
    assert tool_call_row.result["_artifact_storage"] == "external_json_gzip"
    assert tool_call_row.result["artifact_id"] == executed.tool_result["artifact_id"]
    assert loaded_payload["result"] == huge_result
