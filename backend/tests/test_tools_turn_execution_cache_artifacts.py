"""The session tool cache for Kubernetes reads and log queries and persisted artifact envelopes."""

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.agent.core.turn.turn_diff import TurnDiffTracker
from app.agent.core.turn.turn_tools import execute_tool_call_for_turn
from app.models import Message, Session, SessionToolCacheEntry, User
from app.services.tool_artifact import (
    parse_tool_artifact_envelope,
)
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_execute_tool_call_for_turn_uses_session_cache_for_k8s_reads(db):
    turn_diff_tracker = TurnDiffTracker()
    execution_count = {"count": 0}
    session_id = str(uuid.uuid4())

    async def fake_execute_tool(tool_name, tool_args, tool_context):
        execution_count["count"] += 1
        return {"source": "api", "namespace": "prod", "failed_count": 2}

    kwargs = dict(
        db=db,
        assistant_message_id=str(uuid.uuid4()),
        tool_call={
            "id": "call-k8s",
            "function": {
                "name": "list_failed_pods",
                "arguments": json.dumps({"namespace": "prod"}),
            },
        },
        tool_context=ToolContext(
            user_id="u1",
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
        turn_diff_tracker=turn_diff_tracker,
        context_snapshot={},
    )

    first = await execute_tool_call_for_turn(**kwargs)
    second = await execute_tool_call_for_turn(**kwargs)

    assert first.tool_result["result"]["failed_count"] == 2
    assert second.tool_result["result"]["failed_count"] == 2
    assert second.tool_result["cache"]["status"] == "hit"
    assert second.tool_result["cache"]["hit_count"] == 1
    assert execution_count["count"] == 1

    cache_rows = (
        (
            await db.execute(
                select(SessionToolCacheEntry).where(
                    SessionToolCacheEntry.session_id == session_id,
                    SessionToolCacheEntry.tool_name == "list_failed_pods",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(cache_rows) == 1
    assert cache_rows[0].ttl_seconds == 60
    assert cache_rows[0].hit_count == 1


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_execute_tool_call_for_turn_persists_artifact_envelope_and_loads_detail(db):
    turn_diff_tracker = TurnDiffTracker()
    session_id = str(uuid.uuid4())
    assistant_message_id = str(uuid.uuid4())
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=session_id, user_id=admin.id, metadata_={})
    db.add(session)
    db.add(Message(id=assistant_message_id, session_id=session_id, role="assistant", content="tool"))
    await db.commit()

    async def fake_execute_tool(tool_name, tool_args, tool_context):
        return {
            "status": "ok",
            "summary": "deploy health",
            "items": [{"name": "api", "state": "ready"}, {"name": "worker", "state": "ready"}],
        }

    context = ToolContext(
        user_id=admin.id,
        project_ids=[],
        roles=["admin"],
        session_id=session_id,
        project_config={},
        db=db,
        workspace_root=str(Path.cwd()),
    )

    executed = await execute_tool_call_for_turn(
        db=db,
        assistant_message_id=assistant_message_id,
        tool_call={
            "id": "call-artifact",
            "function": {
                "name": "todo_read",
                "arguments": json.dumps({}),
            },
        },
        tool_context=context,
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
        turn_diff_tracker=turn_diff_tracker,
        context_snapshot={},
    )

    artifact_id = executed.tool_result["artifact_id"]
    envelope = parse_tool_artifact_envelope(executed.message_for_model["content"])
    assert envelope is not None
    assert envelope["artifact_id"] == artifact_id
    assert envelope["tool_name"] == "todo_read"
    assert "result" in envelope

    loaded = await execute_tool(
        "load_tool_artifact",
        {"artifact_id": artifact_id, "detail_level": "excerpt", "max_items": 1},
        context,
    )

    assert loaded["artifact_id"] == artifact_id
    assert loaded["tool_name"] == "todo_read"
    assert loaded["detail_level"] == "excerpt"
    assert loaded["result"]["items"][-1] == "... (1 more items)"

    segment = await execute_tool(
        "load_tool_artifact",
        {"artifact_id": artifact_id, "path": "items.0", "detail_level": "excerpt"},
        context,
    )
    assert segment["path"] == "items.0"
    assert segment["result"]["name"] == "api"


@pytest.mark.asyncio
async def test_execute_tool_call_for_turn_does_not_cache_log_queries(db):
    turn_diff_tracker = TurnDiffTracker()
    execution_count = {"count": 0}
    session_id = str(uuid.uuid4())

    async def fake_execute_tool(tool_name, tool_args, tool_context):
        execution_count["count"] += 1
        return {"query": '{service="api"}', "total_lines": 1, "streams_count": 1, "streams": []}

    kwargs = dict(
        db=db,
        assistant_message_id=str(uuid.uuid4()),
        tool_call={
            "id": "call-loki",
            "function": {
                "name": "query_loki",
                "arguments": json.dumps({"query": '{service="api"}', "limit": 50}),
            },
        },
        tool_context=ToolContext(
            user_id="u1",
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
        turn_diff_tracker=turn_diff_tracker,
        context_snapshot={},
    )

    first = await execute_tool_call_for_turn(**kwargs)
    second = await execute_tool_call_for_turn(**kwargs)

    assert "cache" not in first.tool_result
    assert "cache" not in second.tool_result
    assert execution_count["count"] == 2

    cache_rows = (
        (await db.execute(select(SessionToolCacheEntry).where(SessionToolCacheEntry.session_id == session_id)))
        .scalars()
        .all()
    )
    assert cache_rows == []
