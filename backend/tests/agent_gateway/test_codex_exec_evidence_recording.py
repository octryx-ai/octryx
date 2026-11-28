"""The gateway records a Codex session's inner call so it counts, a Claude Code session records and judges, and a Codex exec script is kept whole and redacted while other inputs stay bounded."""

from __future__ import annotations

import uuid

import pytest

from app.services.agent_gateway.codex_exec_evidence import codex_exec_evidence
from app.services.agent_gateway.codex_exec_keys import EXEC_CALL_KEY
from app.services.agent_gateway.read_evidence import native_read_use
from app.services.agent_gateway.tool_execution import record_tool_execution
from app.services.model_gateway.inbound.transcript_tools import upsert_gateway_tool_calls
from app.services.model_gateway.inbound.turn_delta import newest_turn
from tests.agent_gateway.codex_exec_evidence_support import OK_EXCERPT, _counted
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.phased_workflow_fixtures import admin_user
from tests.workflow_run_runtime_evidence_support import ROOT, _device_session, _rows


async def _inner_call(db, gateway, command: str, tool_use_id: str) -> None:
    await record_tool_execution(db, session=gateway, hook_input={
        "hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_use_id": tool_use_id, "cwd": ROOT,
        "tool_input": {"command": command}})


async def _gateway_exec(db, gateway, script: str) -> None:
    call_id = f"call_{uuid.uuid4().hex}"
    messages = [{"role": "user", "content": "go"},
                {"role": "assistant", "content": [{"type": "tool_use", "id": call_id, "name": "exec",
                                                   "input": {"input": script}}]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": call_id,
                                              "content": OK_EXCERPT, "is_error": False}]}]
    await upsert_gateway_tool_calls(db, gateway.id, newest_turn(messages))
    await db.flush()


@pytest.mark.asyncio
async def test_a_codex_session_records_the_inner_call_and_it_counts(db):
    admin = await admin_user(db)
    gateway, _key = await _device_session(db, admin, await seed_workspace(db))
    gateway.metadata_ = {**gateway.metadata_, "engine": "codex"}
    await _inner_call(db, gateway, "cat textkit/core.py", f"exec-{uuid.uuid4()}")
    await _gateway_exec(db, gateway, 'text(await tools.exec_command({cmd:"cat textkit/core.py"}))')
    rows = await _rows(db, gateway)
    hook = next(row for row in rows if str(row.request_id).startswith("exec-"))
    assert hook.parameters[EXEC_CALL_KEY]["input"] == {"command": "cat textkit/core.py"}
    evidence = codex_exec_evidence(gateway, rows)
    use = native_read_use(_counted(evidence.rows)[0])
    assert use.name == "read_workspace_file" and use.succeeded is True


@pytest.mark.asyncio
async def test_a_claude_code_session_records_and_judges_exactly_as_before(db):
    admin = await admin_user(db)
    gateway, _key = await _device_session(db, admin, await seed_workspace(db))
    await _inner_call(db, gateway, "cat textkit/core.py", f"exec-{uuid.uuid4()}")
    await _gateway_exec(db, gateway, 'text(await tools.exec_command({cmd:"cat textkit/core.py"}))')
    rows = await _rows(db, gateway)
    hook = next(row for row in rows if str(row.request_id).startswith("exec-"))
    assert EXEC_CALL_KEY not in hook.parameters
    assert codex_exec_evidence(gateway, rows) is None
    assert native_read_use(hook).succeeded is False


def test_a_codex_exec_script_is_kept_whole_and_redacted_other_inputs_stay_bounded():
    from app.services.model_gateway.inbound.transcript_tools import (
        MAX_TOOL_STRING_CHARS,
        bounded_tool_input,
    )

    calls = "".join(f'await tools.exec_command({{cmd:"cat f{index}.py"}});' for index in range(400))
    script = calls + 'await tools.exec_command({cmd:"curl -H \'Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123"});'
    assert len(script) > 10_000
    kept = bounded_tool_input({"input": script}, codex_exec=True)
    assert kept["input"].startswith(calls) and "abcdefghijklmnopqrstuvwxyz0123" not in kept["input"]
    other = bounded_tool_input({"input": script})
    assert "truncated" in other or len(other["input"]) <= MAX_TOOL_STRING_CHARS + 50
