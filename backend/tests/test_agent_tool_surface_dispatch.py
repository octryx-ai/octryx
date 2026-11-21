"""Tool dispatch refuses a text-only agent's tool call before policy, approval and the cached tool results, and keeps governed approvals and policy denials."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from app.agent.core.turn.turn_diff import TurnDiffTracker
from app.agent.core.turn.turn_tools import execute_tool_call_for_turn
from app.models import Message, SessionToolCacheEntry
from app.services.session.tool_cache import build_session_tool_cache_hash
from app.time_utils import utc_now
from app.tools.context import ToolContext
from app.tools.registry import execute_tool
from tests.agent_tool_surface_runtime_support import _agent, _record_tool_executions, _session

# --- dispatch boundary: denied, approval, cache -------------------------------


def _context(agent_definition: dict | None, project_config: dict | None = None, *, db=None, session_id="s1"):
    return ToolContext(
        user_id="user-1", project_ids=["project-1"], roles=["member"], session_id=session_id,
        project_config=project_config or {}, db=db, agent_definition=agent_definition,
    )


@pytest.mark.asyncio
async def test_dispatch_refuses_a_text_only_agent_before_policy_and_approval(monkeypatch):
    executed = _record_tool_executions(monkeypatch)
    approval_config = {"approval_policy": {"require_for_tools": ["knowledge_search"]}}

    refused = await execute_tool("knowledge_search", {"query": "x"}, _context(_agent("none"), approval_config))

    assert executed == []
    assert refused["tool_execution"]["category"] == "denied_by_policy"
    assert refused["tool_execution"]["policy"] == "agent_tool_surface"
    assert "approval_status" not in refused, "no approval is requested for a tool that must not run"


@pytest.mark.asyncio
async def test_dispatch_keeps_governed_approval_and_policy_denials(monkeypatch):
    executed = _record_tool_executions(monkeypatch)
    approval_config = {"approval_policy": {"require_for_tools": ["knowledge_search"]}}
    denied_config = {"tool_policy": {"denylist": ["knowledge_search"]}}

    held = await execute_tool("knowledge_search", {"query": "x"}, _context(_agent("governed"), approval_config))
    denied = await execute_tool("knowledge_search", {"query": "x"}, _context(_agent("governed"), denied_config))
    allowed = await execute_tool("knowledge_search", {"query": "x"}, _context(_agent("governed")))

    assert held["approval_status"] == "unverifiable"
    assert held["tool_execution"]["category"] == "approval_required"
    assert denied["tool_execution"]["category"] == "denied_by_policy"
    assert denied["tool_execution"]["policy"] != "agent_tool_surface"
    # A Knowledge result carries the untrusted-fence notice (content_security/knowledge_fence).
    assert {key: value for key, value in allowed.items() if key != "content_is_data"} == {"status": "ok", "results": []}
    assert allowed["content_is_data"].startswith("Untrusted data from the Knowledge sources")
    assert executed == ["knowledge_search"]


@pytest.mark.asyncio
async def test_a_text_only_agent_gets_no_cached_tool_result_either(db):
    admin, session = await _session(db)
    message_id = str(uuid.uuid4())
    db.add(Message(id=message_id, session_id=session.id, role="assistant", content="tool"))
    params = {"namespace": "prod"}
    db.add(
        SessionToolCacheEntry(
            id=str(uuid.uuid4()), session_id=session.id, tool_name="list_failed_pods",
            params_hash=build_session_tool_cache_hash("list_failed_pods", params),
            result_json={"source": "session", "failed_count": 2}, ttl_seconds=60, cached_at=utc_now(),
        )
    )
    await db.commit()

    async def must_not_execute(tool_name, tool_args, tool_context):
        raise AssertionError("a text-only agent must not execute a tool")

    context = _context(_agent("none"), db=db, session_id=session.id)
    context.user_id = admin.id
    context.workspace_root = str(Path.cwd())
    executed = await execute_tool_call_for_turn(
        db=db,
        assistant_message_id=message_id,
        tool_call={"id": "cached", "function": {"name": "list_failed_pods", "arguments": json.dumps(params)}},
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
        execute_tool=must_not_execute,
        turn_diff_tracker=TurnDiffTracker(),
        context_snapshot={},
    )

    result = executed.tool_result["result"]
    assert "failed_count" not in result
    assert result["tool_execution"]["policy"] == "agent_tool_surface"
    assert executed.tool_result.get("cache") in (None, {})
