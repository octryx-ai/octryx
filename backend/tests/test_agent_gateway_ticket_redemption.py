from __future__ import annotations

import json
import time
import uuid

import pytest
from sqlalchemy import select

from app.db import Base
from app.models import Project, Session, SessionTranscriptChunk, ToolCall
from app.services.agent_gateway.confirmation import (
    TOOL_CALL_STATUS_CONFIRMATION_CONSUMED,
    WORKFLOW_CONFIRM_HOOK_TOOL,
    ask_for_confirmation,
    redeem_confirmation_ticket,
)
from app.services.agent_gateway.decision_confirmation import redeem_decision_ticket
from app.services.agent_gateway.tool_check import DECISION_DENY, ToolDecision, record_denial
from app.services.agent_gateway.tool_execution import record_tool_execution
from app.services.devices.job_events import apply_event, store_event
from app.services.mcp_workflow_tools import mcp_workflow_confirm
from app.services.model_gateway.inbound.transcript_tools import upsert_gateway_tool_calls
from app.services.model_gateway.inbound.turn_delta import ToolResultBlock, ToolUseBlock, TurnDelta
from app.services.session_transcripts.store import TranscriptBatch, read_chunk_lines, store_batch
from app.services.workflow_runs.octryx.decisions import arguments_digest
from tests.agent_gateway_hook_support import confirm_hook_input
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.services.agent_gateway.test_agent_gateway_confirmation_security import _setup
from tests.session_transcripts.transcript_store_support import artifact_dir  # noqa: F401 - autouse fixture
from tests.test_workflow_run_octryx_decisions import CONFIRM, _terminal
from tests.workflow_run_octryx_continuation_support import (  # noqa: F401 - _hub autouse
    _confirm,
    _device_run,
    _hub,
    _jobs,
)

pytestmark = pytest.mark.usefixtures("scripted_pool")


async def _confirmation_ticket(db, gateway, session_key, approval_id, key) -> tuple[str, dict]:
    hook_input = confirm_hook_input(key, session_key=session_key, approval_id=approval_id)
    asked = await ask_for_confirmation(db, session=gateway, session_key=session_key, hook_input=hook_input)
    return asked["confirmation_ticket"], hook_input


async def test_a_confirmation_ticket_redeemed_a_second_time_is_refused(db):
    _, _, gateway, session_key, _, approval_id, key = await _setup(db)
    ticket, hook_input = await _confirmation_ticket(db, gateway, session_key, approval_id, key)
    values = {"approval_id": approval_id, "ticket": ticket, "tool_use_id": hook_input["tool_use_id"]}

    assert await redeem_confirmation_ticket(db, session=gateway, **values) is True
    assert await redeem_confirmation_ticket(db, session=gateway, **values) is False
    [row] = (await db.execute(select(ToolCall).where(ToolCall.session_id == gateway.id,
                                                     ToolCall.tool_name == WORKFLOW_CONFIRM_HOOK_TOOL))).scalars()
    assert row.status == TOOL_CALL_STATUS_CONFIRMATION_CONSUMED


async def test_a_decision_ticket_redeemed_a_second_time_is_refused(db):
    terminal = await _terminal(db, CONFIRM)
    tool_input = {"action": "confirm", "payload_hash": terminal.run.node_state["waiting"]["payload_hash"]}
    ticket = (await terminal.pre_tool_use(tool_input))["confirmation_ticket"]
    values = {"run_id": terminal.run.id, "action": "confirm", "payload_hash": tool_input["payload_hash"],
              "arguments_digest": arguments_digest(tool_input), "ticket": ticket, "tool_use_id": "toolu_decide_1"}

    assert await redeem_decision_ticket(db, session=terminal.gateway, **values) is True
    assert await redeem_decision_ticket(db, session=terminal.gateway, **values) is False


async def _stored_text(db) -> str:
    rows = []
    for table in Base.metadata.sorted_tables:
        rows.extend(repr(tuple(row)) for row in (await db.execute(select(table))).all())
    return "\n".join(rows)


async def test_no_stored_row_or_transcript_line_keeps_the_raw_ticket(db):
    workspace_id, user, gateway, session_key, caller, approval_id, key = await _setup(db)
    ticket, hook_input = await _confirmation_ticket(db, gateway, session_key, approval_id, key)
    confirmed_input = {"approval_id": approval_id, "confirmation_ticket": ticket}
    tool_use_id = hook_input["tool_use_id"]

    answer = await mcp_workflow_confirm(db, caller=caller, user=user, workspace_id=workspace_id,
                                        arguments=confirmed_input)
    assert answer["state"] == "selected"
    delta = TurnDelta(user_texts=(), tool_results=(ToolResultBlock(tool_use_id, False, "selected"),),
                      prior_tool_uses=(ToolUseBlock(tool_use_id, WORKFLOW_CONFIRM_HOOK_TOOL, 0, confirmed_input),))
    await upsert_gateway_tool_calls(db, gateway.id, delta)
    post = {"hook_event_name": "PostToolUse", "tool_name": WORKFLOW_CONFIRM_HOOK_TOOL, "tool_use_id": tool_use_id,
            "tool_input": confirmed_input}
    await record_tool_execution(db, session=gateway, hook_input=post)
    denied = {**post, "hook_event_name": "PreToolUse", "tool_use_id": "toolu_denied_1"}
    await record_denial(db, session=gateway, hook_input=denied,
                        decision=ToolDecision(DECISION_DENY, "denied", "local_decision", "local:local_decision", ""))

    project = await db.get(Project, workspace_id)
    project.config = {**(project.config or {}), "agent_gateway_policy": {"session_transcripts": {"enabled": True}}}
    tool_use = {"type": "tool_use", "id": tool_use_id, "name": WORKFLOW_CONFIRM_HOOK_TOOL, "input": confirmed_input}
    lines = [{"type": "assistant", "message": {"role": "assistant", "content": [tool_use]}},
             {"type": "user", "message": {"role": "user", "content": [
                 {"type": "text", "text": json.dumps({"tool_input": confirmed_input})}]}}]
    batch = TranscriptBatch(claude_session_id=str(uuid.uuid4()), stream="main", first_line=0, lines=lines)
    stored = await store_batch(db, session=await db.get(Session, gateway.id), batch=batch)
    assert stored["state"] == "stored"
    await db.flush()

    [chunk] = (await db.execute(select(SessionTranscriptChunk).where(
        SessionTranscriptChunk.session_id == gateway.id))).scalars()
    assert ticket not in json.dumps(await read_chunk_lines(chunk))
    recorded = (await db.execute(select(ToolCall).where(ToolCall.session_id == gateway.id))).scalars().all()
    assert any(tool_use_id == row.request_id for row in recorded)
    assert ticket not in await _stored_text(db)


async def test_no_device_job_event_or_approval_keeps_the_raw_ticket(db):
    workspace_id, user, gateway, session_key, caller, approval_id, key = await _setup(db)
    ticket, _ = await _confirmation_ticket(db, gateway, session_key, approval_id, key)
    confirmed_input = {"approval_id": approval_id, "confirmation_ticket": ticket}
    admin, _device, thread, run = await _device_run(db)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    preview = json.dumps(confirmed_input)
    events = [
        ("approval_request", {"turn_id": job.turn_id, "approval_id": "ap-ticket", "tool": WORKFLOW_CONFIRM_HOOK_TOOL,
                              "input_preview": preview, "expires_at": time.time() + 300}),
        ("job_event", {"turn_id": job.turn_id, "kind": "tool_use", "tool": WORKFLOW_CONFIRM_HOOK_TOOL,
                       "tool_use_id": "toolu_device_1", "input_preview": preview}),
    ]
    for message_type, body in events:
        seq = int(job.last_event_seq or 0) + 1
        await store_event(db, job, seq, message_type, body)
        await apply_event(db, job, message_type, body, limits={"approval_timeout_s": 300})

    answer = await mcp_workflow_confirm(db, caller=caller, user=user, workspace_id=workspace_id,
                                        arguments=confirmed_input)
    assert answer["state"] == "selected"
    await db.flush()
    stored = await _stored_text(db)
    assert "ap-ticket" in stored and "toolu_device_1" in stored
    assert ticket not in stored
