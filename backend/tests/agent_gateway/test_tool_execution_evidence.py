"""Contract: the verification gate tells "test not run" from "test failed" by execution evidence.

Evidence comes from the launcher's PostToolUse / PostToolUseFailure hooks
(``POST sessions/tool-executed``), never from the tool result's text. The hook and
the model gateway's transcript writer converge on one ToolCall row per tool_use id,
in either order.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import ToolCall
from app.services.agent_gateway.policy import build_policy
from app.services.agent_gateway.policy_normalize import normalize_agent_gateway_policy
from app.services.agent_gateway.tool_execution import execution_evidence
from app.services.agent_gateway.verification import evaluate_verification
from app.services.model_gateway.inbound.transcript_tools import _upsert_tool_calls
from app.services.model_gateway.inbound.turn_delta import ToolResultBlock, ToolUseBlock, TurnDelta
from app.time_utils import utc_now
from tests.test_agent_gateway_control_plane import BASE, VERIFYING_POLICY, _gateway, _workspace

POLICY = build_policy(normalize_agent_gateway_policy(VERIFYING_POLICY), source="workspace")
TEST_COMMAND = "python -m pytest tests/x.py"


def _row(tool: str, *, seconds: int, is_error: bool | None, command: str = "", executed: str | None = None):
    parameters = {"source": "model_gateway", "tool_use_id": uuid.uuid4().hex, "block_index": 0, "input": {}}
    if command:
        parameters["command"] = command
    if executed:
        parameters["executed"] = execution_evidence(executed)
    status = "requested" if is_error is None else ("error" if is_error else "success")
    result = None if is_error is None else {"is_error": is_error, "excerpt": ""}
    return ToolCall(
        session_id="s",
        tool_name=tool,
        parameters=parameters,
        result=result,
        status=status,
        created_at=utc_now() + timedelta(seconds=seconds),
    )


@pytest.mark.parametrize(
    ("is_error", "executed", "expected"),
    [
        (True, None, ("blocked", "last_test_not_run")),
        (True, "failed", ("blocked", "last_test_failed")),
        (False, "failed", ("blocked", "last_test_failed")),
        (True, "succeeded", ("blocked", "last_test_failed")),
        (False, "succeeded", ("passed", "green_test_after_last_change")),
        (False, None, ("passed", "green_test_after_last_change")),
        (None, "succeeded", ("blocked", "last_test_unconfirmed")),
    ],
)
def test_the_last_test_is_judged_by_its_result_and_execution_evidence(is_error, executed, expected):
    rows = [
        _row("Edit", seconds=0, is_error=False),
        _row("Bash", seconds=1, is_error=is_error, command=TEST_COMMAND, executed=executed),
    ]
    result = evaluate_verification(POLICY, rows)
    assert (result.state, result.reason) == expected
    if expected[1] == "last_test_not_run":
        assert result.detail.startswith("Octryx gate: the focused test did not run")


def _post_tool_use(event: str, tool_use_id: str) -> dict:
    return {
        "hook_event_name": event,
        "session_id": "claude-local",
        "tool_name": "Bash",
        "tool_input": {"command": TEST_COMMAND},
        "tool_use_id": tool_use_id,
        "tool_response": {"stdout": "3 passed"},
    }


def _delta(edit_id: str, bash_id: str, *, with_results: bool) -> TurnDelta:
    uses = (
        ToolUseBlock(edit_id, "Edit", 0, {"file_path": "a.py", "old_string": "x", "new_string": "y"}),
        ToolUseBlock(bash_id, "Bash", 1, {"command": TEST_COMMAND}),
    )
    results = (ToolResultBlock(edit_id, False, "ok"), ToolResultBlock(bash_id, False, "3 passed"))
    return TurnDelta(user_texts=(), tool_results=results if with_results else (), prior_tool_uses=uses)


@pytest.mark.asyncio
@pytest.mark.parametrize("hook_first", [True, False])
async def test_hook_evidence_and_gateway_transcript_converge_on_one_row(client, db, hook_first):
    headers, session = await _gateway(db, await _workspace(db, policy=VERIFYING_POLICY))
    edit_id, bash_id = f"toolu_{uuid.uuid4().hex[:12]}", f"toolu_{uuid.uuid4().hex[:12]}"

    async def hook() -> dict:
        response = await client.post(
            f"{BASE}/sessions/tool-executed", headers=headers, json=_post_tool_use("PostToolUse", bash_id)
        )
        assert response.status_code == 200, response.text
        return response.json()

    if hook_first:
        # The live order: the hook runs before the next model call carries tool_use + tool_result.
        assert (await hook())["reason"] == "execution_recorded_new_row"
        await _upsert_tool_calls(db, session.id, _delta(edit_id, bash_id, with_results=True))
        await db.commit()
    else:
        await _upsert_tool_calls(db, session.id, _delta(edit_id, bash_id, with_results=False))
        await db.commit()
        assert (await hook())["reason"] == "execution_recorded_existing_row"
        await _upsert_tool_calls(db, session.id, _delta(edit_id, bash_id, with_results=True))
        await db.commit()

    session_id = session.id
    rows = (
        await db.execute(
            select(ToolCall).where(ToolCall.session_id == session_id).execution_options(populate_existing=True)
        )
    ).scalars().all()
    by_id = {row.request_id: row for row in rows}
    assert len(rows) == 2 and set(by_id) == {edit_id, bash_id}
    bash = by_id[bash_id]
    assert bash.parameters["executed"] == {"outcome": "succeeded", "source": "client_hook"}
    assert (bash.parameters["block_index"], bash.parameters["command"]) == (1, TEST_COMMAND)
    assert (bash.status, bash.result["is_error"]) == ("success", False)
    assert "tool_response" not in str(bash.parameters) and "3 passed" not in str(bash.parameters)
    # One assistant message, one created_at: block_index orders the Edit before the test.
    assert bash.created_at == by_id[edit_id].created_at

    verified = await client.post(
        f"{BASE}/sessions/verification", headers=headers, json={"hook_event_name": "Stop", "stop_hook_active": False}
    )
    assert (verified.json()["state"], verified.json()["reason"]) == ("passed", "green_test_after_last_change")


@pytest.mark.asyncio
async def test_tool_executed_refuses_unknown_events_and_invalid_ids(client, db):
    headers, session = await _gateway(db, await _workspace(db))
    unsupported = await client.post(
        f"{BASE}/sessions/tool-executed", headers=headers, json=_post_tool_use("PreToolUse", "toolu_1")
    )
    invalid = await client.post(
        f"{BASE}/sessions/tool-executed", headers=headers, json=_post_tool_use("PostToolUseFailure", "../x")
    )
    assert (unsupported.status_code, unsupported.headers["x-octryx-gateway-reason"]) == (
        400,
        "hook_event_unsupported",
    )
    assert (invalid.status_code, invalid.headers["x-octryx-gateway-reason"]) == (400, "tool_use_id_invalid")
    assert (await db.execute(select(ToolCall).where(ToolCall.session_id == session.id))).scalars().all() == []
