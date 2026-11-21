import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.agent.core.turn.turn_diff import TurnDiffTracker
from app.agent.core.turn.turn_tools import execute_tool_call_for_turn
from app.models import Message, Session, User
from app.services.tool_artifact import parse_tool_artifact_envelope
from app.services.tool_result_compression import (
    MAX_COMPACT_RESULT_TOKENS,
    compress_tool_result_for_model,
)
from app.services.tool_result_compression.support import _estimate_tokens
from app.tools.context import ToolContext


@pytest.mark.asyncio
async def test_fallback_tool_result_compression_stays_within_global_hard_cap(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    huge_result = {
        "content": "x" * 40000,
        "items": [{"value": "y" * 2000} for _ in range(200)],
    }

    compressed = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="unknown_large_tool",
        result=huge_result,
        fallback=lambda _tool_name, result: result,
    )

    assert compressed["_hard_capped"] is True
    assert _estimate_tokens(compressed) <= MAX_COMPACT_RESULT_TOKENS


@pytest.mark.asyncio
async def test_fallback_tool_result_compression_summarizes_extreme_nested_payloads(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    huge_result = {
        f"section_{index}": {
            "content": "x" * 16000,
            "items": [{"value": "y" * 3000, "index": item} for item in range(40)],
        }
        for index in range(60)
    }

    compressed = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="unknown_extreme_tool",
        result=huge_result,
        fallback=lambda _tool_name, result: result,
    )

    assert compressed["_hard_capped"] is True
    assert _estimate_tokens(compressed) <= MAX_COMPACT_RESULT_TOKENS
    assert compressed.get("_original_type") in {"dict", None}


@pytest.mark.asyncio
async def test_execute_tool_call_for_turn_hard_caps_large_compact_results_for_model_payload(db):
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
            "content": "x" * 50000,
            "items": [{"name": f"item-{index}", "value": "y" * 4000} for index in range(120)],
        }

    executed = await execute_tool_call_for_turn(
        db=db,
        assistant_message_id=assistant_message_id,
        tool_call={
            "id": "call-huge-artifact",
            "function": {
                "name": "todo_read",
                "arguments": json.dumps({}),
            },
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
        turn_diff_tracker=turn_diff_tracker,
        context_snapshot={},
    )

    assert executed.tool_result["compact_result"]["_hard_capped"] is True
    assert _estimate_tokens(executed.tool_result["compact_result"]) <= 2200

    envelope = parse_tool_artifact_envelope(executed.message_for_model["content"])
    assert envelope is not None
    assert envelope["result"]["_hard_capped"] is True
    assert _estimate_tokens(envelope["result"]) <= 2200
