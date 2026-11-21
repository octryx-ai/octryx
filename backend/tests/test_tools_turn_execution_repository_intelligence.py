"""Code and workflow plan writes with and without prior repository intelligence."""

import json
import uuid
from pathlib import Path

import pytest

from app.agent.core.turn.turn_diff import TurnDiffTracker
from app.agent.core.turn.turn_tools import execute_tool_call_for_turn
from app.tools.context import ToolContext


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_execute_tool_call_for_turn_blocks_code_write_without_prior_repository_intelligence(db):
    execution_count = {"count": 0}

    async def fake_execute_tool(tool_name, tool_args, tool_context):
        execution_count["count"] += 1
        return {"status": "ok"}

    result = await execute_tool_call_for_turn(
        db=db,
        assistant_message_id=str(uuid.uuid4()),
        tool_call={
            "id": "call-write-blocked",
            "function": {
                "name": "write_workspace_file",
                "arguments": json.dumps({"path": "src/app.py", "content": "print('hi')\n"}),
            },
        },
        tool_context=ToolContext(
            user_id="u1",
            project_ids=[],
            roles=["admin"],
            session_id=str(uuid.uuid4()),
            project_config={},
            db=db,
            workspace_root=str(Path.cwd()),
            capability_type="change",
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
        turn_tool_history=[],
    )

    assert execution_count["count"] == 0
    assert result.tool_result["result"]["guardrail"] == "coding_prewrite_intelligence_required"
    assert "analyze_workspace_repository" in result.tool_result["result"]["suggested_next_tools"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_execute_tool_call_for_turn_allows_code_write_after_repository_intelligence(db):
    execution_count = {"count": 0}

    async def fake_execute_tool(tool_name, tool_args, tool_context):
        execution_count["count"] += 1
        return {"status": "ok", "path": tool_args.get("path")}

    await execute_tool_call_for_turn(
        db=db,
        assistant_message_id=str(uuid.uuid4()),
        tool_call={
            "id": "call-write-allowed",
            "function": {
                "name": "write_workspace_file",
                "arguments": json.dumps({"path": "src/app.py", "content": "print('hi')\n"}),
            },
        },
        tool_context=ToolContext(
            user_id="u1",
            project_ids=[],
            roles=["admin"],
            session_id=str(uuid.uuid4()),
            project_config={},
            db=db,
            workspace_root=str(Path.cwd()),
            capability_type="change",
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
        turn_tool_history=[{"tool_name": "analyze_workspace_repository", "result": {"status": "ok"}}],
    )

    assert execution_count["count"] == 1


@pytest.mark.asyncio
async def test_execute_tool_call_for_turn_allows_workflow_plan_write_without_repository_intelligence(db):
    execution_count = {"count": 0}

    async def fake_execute_tool(tool_name, tool_args, tool_context):
        execution_count["count"] += 1
        return {"status": "ok", "path": tool_args.get("path")}

    result = await execute_tool_call_for_turn(
        db=db,
        assistant_message_id=str(uuid.uuid4()),
        tool_call={
            "id": "call-write-plan",
            "function": {
                "name": "write_workspace_file",
                "arguments": json.dumps(
                    {"path": "ticketing_research_document_plan.json", "content": "{\"sections\": []}\n"}
                ),
            },
        },
        tool_context=ToolContext(
            user_id="u1",
            project_ids=[],
            roles=["admin"],
            session_id=str(uuid.uuid4()),
            project_config={},
            db=db,
            workspace_root=str(Path.cwd()),
            capability_type="change",
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
        turn_tool_history=[],
    )

    assert execution_count["count"] == 1
    assert result.tool_result["result"]["status"] == "ok"
