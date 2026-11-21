"""Blocking low-credibility source ingests."""

import json
import uuid
from pathlib import Path

import pytest

from app.agent.core.turn.turn_diff import TurnDiffTracker
from app.agent.core.turn.turn_tools import execute_tool_call_for_turn
from app.tools.context import ToolContext


@pytest.mark.asyncio
async def test_execute_tool_call_for_turn_blocks_low_credibility_delegated_documentation_source_ingest(db):
    execution_count = {"count": 0}

    async def fake_execute_tool(tool_name, tool_args, tool_context):
        execution_count["count"] += 1
        return {"status": "ok"}

    result = await execute_tool_call_for_turn(
        db=db,
        assistant_message_id=str(uuid.uuid4()),
        tool_call={
            "id": "call-ingest-low-credibility-delegated-source",
            "function": {
                "name": "ingest_document_source",
                "arguments": json.dumps(
                    {
                        "url": "https://blog-b.example/best-practices-for-a-successful-ticketing-system-"
                        "implementation/",
                    }
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
            capability_type="documentation",
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
        context_snapshot={
            "agent": {"type": "documentation"},
            "current_step": {"name": "Gather Delegated Evidence"},
            "request_analysis": {
                "canonical_message": "Research official Jira REST API integration guidance for ticketing API integration.",
            },
        },
        turn_tool_history=[],
    )

    assert execution_count["count"] == 0
    assert result.tool_result["result"]["guardrail"] == "technical_source_credibility_required"
    assert result.tool_result["result"]["blocked_url"] == (
        "https://blog-b.example/best-practices-for-a-successful-ticketing-system-implementation/"
    )
