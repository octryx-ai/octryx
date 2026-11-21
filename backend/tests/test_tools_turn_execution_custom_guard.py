"""Custom exec guards audit tool calls with and without blocking them."""

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.agent.core.turn.turn_diff import TurnDiffTracker
from app.agent.core.turn.turn_tools import execute_tool_call_for_turn
from app.models import AuditLog, User
from app.services.exec_policy import upsert_global_exec_policy_config
from app.tools.context import ToolContext


@pytest.mark.asyncio
async def test_execute_tool_call_for_turn_audits_custom_guard_without_blocking_execution(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    await upsert_global_exec_policy_config(
        db,
        {
            "custom_tool_guard_rules": [
                {
                    "id": "audit-person-research",
                    "label": "Audit person research lookups",
                    "description": "Person research lookups are visible to security audit.",
                    "tool_names": ["todo_read"],
                    "conditions": {"all": [{"field": "args.query", "operator": "contains", "value": "Alice"}]},
                    "action": "audit",
                    "severity": "medium",
                }
            ]
        },
    )
    await db.commit()
    execution_count = {"count": 0}

    async def fake_execute_tool(tool_name, tool_args, tool_context):
        execution_count["count"] += 1
        return {"status": "ok", "query": tool_args["query"]}

    executed = await execute_tool_call_for_turn(
        db=db,
        assistant_message_id=str(uuid.uuid4()),
        tool_call={
            "id": "call-audit-only",
            "function": {
                "name": "todo_read",
                "arguments": json.dumps({"query": "Who is Alice Example?"}),
            },
        },
        tool_context=ToolContext(
            user_id=admin.id,
            project_ids=[],
            roles=["admin"],
            session_id=str(uuid.uuid4()),
            project_config={},
            db=db,
            workspace_root=str(Path.cwd()),
            capability_type="diagnosis",
            request_id="req-audit-only",
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

    audit_log = (
        await db.execute(select(AuditLog).where(AuditLog.action == "agent.guard.audit_matched"))
    ).scalar_one()

    assert execution_count["count"] == 1
    assert executed.tool_result["result"] == {"status": "ok", "query": "Who is Alice Example?"}
    assert audit_log.resource_type == "exec_policy_guard"
    assert audit_log.resource_id == "audit-person-research"
    assert audit_log.details["guard_action"] == "audit"
    assert audit_log.details["tool_name"] == "todo_read"
    assert audit_log.details["tool_args_preview"]["query"] == "Who is Alice Example?"
    assert audit_log.details["request_id"] == "req-audit-only"


@pytest.mark.asyncio
async def test_execute_tool_call_for_turn_audits_custom_guard_block_decision(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    await upsert_global_exec_policy_config(
        db,
        {
            "custom_tool_guard_rules": [
                {
                    "id": "block-sensitive-search",
                    "label": "Block sensitive todo lookup",
                    "tool_names": ["todo_read"],
                    "conditions": {"all": [{"field": "args.query", "operator": "contains", "value": "secret"}]},
                    "action": "block",
                    "severity": "critical",
                }
            ]
        },
    )
    await db.commit()
    execution_count = {"count": 0}

    async def fake_execute_tool(tool_name, tool_args, tool_context):
        execution_count["count"] += 1
        return {"status": "ok"}

    executed = await execute_tool_call_for_turn(
        db=db,
        assistant_message_id=str(uuid.uuid4()),
        tool_call={
            "id": "call-block-audit",
            "function": {
                "name": "todo_read",
                "arguments": json.dumps({"query": "secret deployment notes"}),
            },
        },
        tool_context=ToolContext(
            user_id=admin.id,
            project_ids=[],
            roles=["admin"],
            session_id=str(uuid.uuid4()),
            project_config={},
            db=db,
            workspace_root=str(Path.cwd()),
            capability_type="diagnosis",
            request_id="req-block-audit",
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

    audit_log = (await db.execute(select(AuditLog).where(AuditLog.action == "agent.guard.blocked"))).scalar_one()

    assert execution_count["count"] == 0
    assert executed.tool_result["result"]["guardrail"] == "block-sensitive-search"
    assert executed.tool_result["result"]["exec_policy_action"] == "deny"
    assert audit_log.resource_id == "block-sensitive-search"
    assert audit_log.details["guard_action"] == "block"
    assert audit_log.details["guard_severity"] == "critical"
    assert audit_log.details["tool_call_id"] == "call-block-audit"
