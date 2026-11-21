"""Execution evidence for a governed client tool call (``POST sessions/tool-executed``).

Claude Code fires ``PostToolUse`` after a tool call succeeded and
``PostToolUseFailure`` after a tool that started executing failed. Neither fires for
a call rejected before execution (a refused permission prompt, a PreToolUse deny, a
validation error). The launcher registers both hooks for ``Bash``; each one reports
here, so the verification gate can tell "the test failed" from "the test never ran"
without reading the tool result's text.

The evidence lands on the model-gateway ToolCall row of the same ``tool_use`` id
(``request_id``) in the caller's session as ``parameters["executed"] = {"outcome",
"source"}``; no hook content (command output, error text) is stored. The hook runs
before Claude Code sends the tool result with the next model call, so the row usually
does not exist yet: it is then created with only ``source``, ``tool_use_id`` and
``executed``, and the model gateway merges the tool_use fields into that row
(``model_gateway/inbound/transcript.py``). Each writer only sets its own keys.

For Claude Code's own reads (Read, Grep, Glob, LS) the server also records what was read, derived here from the
hook payload: ``parameters["read_target"]`` (``read_evidence``), the read evidence of a workflow phase.

A Bash call that ran the repository's declared test command may carry the JUnit report that command wrote
(``workflow_run_facts.test_report``: the launcher reads it only when the file changed during this call). It is
stored bounded as ``parameters["test_report"]`` and is the preferred per-test evidence of that call
(``workflow_runs/gateway_tests``).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session, ToolCall
from .contract import (
    EXECUTION_OUTCOME_FAILED,
    EXECUTION_OUTCOME_SUCCEEDED,
    STATE_DENIED,
    STATE_NEEDS_CONFIGURATION,
    TOOL_CALL_EXECUTED_KEY,
    TOOL_CALL_SOURCE_GATEWAY,
    TOOL_CALL_SOURCE_HOOK,
    TOOL_CALL_STATUS_REQUESTED,
)

STATE_RECORDED = "recorded"
REASON_EXECUTION_CREATED = "execution_recorded_new_row"
REASON_EXECUTION_MERGED = "execution_recorded_existing_row"
REASON_HOOK_EVENT_UNSUPPORTED = "hook_event_unsupported"
REASON_TOOL_USE_ID_INVALID = "tool_use_id_invalid"
REASON_TOOL_NAME_INVALID = "tool_name_invalid"

MAX_TOOL_NAME_CHARS = 200
TEST_REPORT_KEY = "test_report"
MAX_TEST_REPORT_CHARS = 1_000_000
_TOOL_USE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_AGENT_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_OUTCOME_BY_EVENT = {
    "PostToolUse": EXECUTION_OUTCOME_SUCCEEDED,
    "PostToolUseFailure": EXECUTION_OUTCOME_FAILED,
}


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    state: str
    reason: str
    http_status: int = 200
    outcome: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {"state": self.state, "reason": self.reason, "outcome": self.outcome}


def execution_evidence(outcome: str) -> dict[str, str]:
    return {"outcome": outcome, "source": TOOL_CALL_SOURCE_HOOK}


def test_report(tool_name: str, hook_input: Mapping[str, Any]) -> dict[str, Any] | None:
    """The JUnit report a Bash test call wrote, as the launcher attached it (bounded), else ``None``."""
    facts = hook_input.get("workflow_run_facts")
    report = facts.get(TEST_REPORT_KEY) if tool_name == "Bash" and isinstance(facts, Mapping) else None
    xml = report.get("junit_xml") if isinstance(report, Mapping) else None
    if not isinstance(xml, str) or "<testcase" not in xml or len(xml) > MAX_TEST_REPORT_CHARS:
        return None
    from ..workflow_checks.test_output import hint_files

    # The test files the launcher found for the report's classnames: hints to key its results canonically.
    files = hint_files(report.get("files") if isinstance(report.get("files"), list) else [])
    # Stored on the tool call: a test that prints a secret into its report never keeps it.
    from ..redaction_policy import redact_secret_text

    return {"format": "junit", "path": str(report.get("path") or "")[:300], "junit_xml": redact_secret_text(xml),
            **({"files": files} if files else {})}


def _gateway_rows(rows: Any) -> list[ToolCall]:
    return [
        row
        for row in rows
        if isinstance(row.parameters, Mapping) and row.parameters.get("source") == TOOL_CALL_SOURCE_GATEWAY
    ]


def _recorded_fields(
    session: Session, hook_input: Mapping[str, Any], tool_name: str, tool_use_id: str
) -> dict[str, Any]:
    """What the row keeps beside the outcome: the sub-agent, the read target, the test report, the exec call."""
    # The Claude Code sub-agent that ran the tool (its SubagentStop reports this child's evidence).
    agent_id = str(hook_input.get("agent_id") or "")
    recorded = {"agent_id": agent_id} if _AGENT_ID.match(agent_id) else {}
    from .read_evidence import READ_TARGET_KEY, read_target

    target = read_target(session, hook_input)
    if target is not None:
        recorded[READ_TARGET_KEY] = target
    report = test_report(tool_name, hook_input)
    if report is not None:
        recorded[TEST_REPORT_KEY] = report
    from .codex_exec_evidence import exec_call_record, is_codex_session, is_exec_inner_id
    from .codex_exec_keys import EXEC_CALL_KEY

    if is_exec_inner_id(tool_use_id) and is_codex_session(session):
        # Codex code mode: what the inner call was, matched against the gateway's exec input (codex_exec_evidence).
        recorded[EXEC_CALL_KEY] = exec_call_record(tool_name, hook_input)
    return recorded


async def record_tool_execution(
    db: AsyncSession, *, session: Session, hook_input: Mapping[str, Any]
) -> ExecutionRecord:
    """Record the hook's execution evidence on the session's row. Flushes only."""

    outcome = _OUTCOME_BY_EVENT.get(str(hook_input.get("hook_event_name") or ""))
    if outcome is None:
        return ExecutionRecord(STATE_NEEDS_CONFIGURATION, REASON_HOOK_EVENT_UNSUPPORTED, 400)
    tool_use_id = hook_input.get("tool_use_id")
    if not isinstance(tool_use_id, str) or not _TOOL_USE_ID.match(tool_use_id):
        return ExecutionRecord(STATE_DENIED, REASON_TOOL_USE_ID_INVALID, 400)
    tool_name = hook_input.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name or len(tool_name) > MAX_TOOL_NAME_CHARS:
        return ExecutionRecord(STATE_DENIED, REASON_TOOL_NAME_INVALID, 400)

    evidence = execution_evidence(outcome)
    recorded = _recorded_fields(session, hook_input, tool_name, tool_use_id)
    rows = _gateway_rows(
        (
            await db.execute(
                select(ToolCall).where(ToolCall.session_id == session.id, ToolCall.request_id == tool_use_id)
            )
        ).scalars()
    )
    if rows:
        for row in rows:
            # A new dict: JSON columns do not track in-place mutation.
            row.parameters = {**row.parameters, TOOL_CALL_EXECUTED_KEY: evidence, **recorded}
        await db.flush()
        return ExecutionRecord(STATE_RECORDED, REASON_EXECUTION_MERGED, outcome=outcome)
    db.add(
        ToolCall(
            id=str(uuid.uuid4()),
            session_id=session.id,
            tool_name=tool_name,
            parameters={
                "source": TOOL_CALL_SOURCE_GATEWAY,
                "tool_use_id": tool_use_id,
                TOOL_CALL_EXECUTED_KEY: evidence,
                **recorded,
            },
            result=None,
            status=TOOL_CALL_STATUS_REQUESTED,
            request_id=tool_use_id,
        )
    )
    await db.flush()
    return ExecutionRecord(STATE_RECORDED, REASON_EXECUTION_CREATED, outcome=outcome)


__all__ = [
    "REASON_EXECUTION_CREATED",
    "REASON_EXECUTION_MERGED",
    "REASON_HOOK_EVENT_UNSUPPORTED",
    "REASON_TOOL_NAME_INVALID",
    "REASON_TOOL_USE_ID_INVALID",
    "STATE_RECORDED",
    "ExecutionRecord",
    "execution_evidence",
    "record_tool_execution",
]
