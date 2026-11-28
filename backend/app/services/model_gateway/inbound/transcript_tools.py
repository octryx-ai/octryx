"""``ToolCall`` rows of one inbound model call and the bounded, redacted tool data they hold (``transcript``)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import ToolCall
from ....time_utils import utc_now
from ...agent_gateway.contract import (
    TOOL_CALL_SOURCE_GATEWAY,
    TOOL_CALL_STATUS_ERROR,
    TOOL_CALL_STATUS_REQUESTED,
    TOOL_CALL_STATUS_SUCCESS,
)
from ...agent_gateway.stored_types import GatewayToolCallParameters
from ...redaction_policy import redact_secret_payload, redact_secret_text
from .turn_delta import ToolUseBlock, TurnDelta

MAX_TOOL_INPUT_CHARS = 4_000
MAX_TOOL_STRING_CHARS = 2_000
MAX_COMMAND_CHARS = 2_000
# Codex code mode (``exec``: one JavaScript input that calls the tools): the whole script, redacted, so every literal
# call in it can be matched (``agent_gateway.codex_exec_evidence``; a cut script makes the
# model repeat work).
CODEX_EXEC_TOOL = "exec"
MAX_EXEC_INPUT_CHARS = 65_536
MAX_TOOL_RESULT_EXCERPT_CHARS = 4_000
BASH_TOOL_NAME = "Bash"


def _redact_tree(value: Any, max_chars: int = MAX_TOOL_STRING_CHARS) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _redact_tree(item, max_chars) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_tree(item, max_chars) for item in value]
    if isinstance(value, str):
        return redact_secret_text(value, max_chars=max_chars)
    return value


def bounded_tool_input(value: Mapping[str, Any], *, codex_exec: bool = False) -> Any:
    string_limit = MAX_EXEC_INPUT_CHARS if codex_exec else MAX_TOOL_STRING_CHARS
    total_limit = MAX_EXEC_INPUT_CHARS + 1_024 if codex_exec else MAX_TOOL_INPUT_CHARS
    # An exec script is masked span by span (``redact_secret_text``): a whole-value redaction would drop every
    # literal call in it together with the one secret.
    source = dict(value) if codex_exec else redact_secret_payload(dict(value), max_string_length=string_limit)
    redacted = _redact_tree(source, string_limit)
    encoded = json.dumps(redacted, ensure_ascii=False, default=str)
    if len(encoded) <= total_limit:
        return redacted
    return {"truncated": True, "excerpt": encoded[:total_limit]}


def result_excerpt(text: Any) -> str:
    # Head and tail: a test runner prints its summary last.
    full = redact_secret_text(text)
    if len(full) <= MAX_TOOL_RESULT_EXCERPT_CHARS:
        return full
    head = MAX_TOOL_RESULT_EXCERPT_CHARS // 3
    tail = MAX_TOOL_RESULT_EXCERPT_CHARS - head
    return f"{full[:head]}\n...[truncated]...\n{full[-tail:]}"


def _tool_use_parameters(use: ToolUseBlock) -> GatewayToolCallParameters:
    parameters: GatewayToolCallParameters = {
        "source": TOOL_CALL_SOURCE_GATEWAY,
        "tool_use_id": use.tool_use_id[:64],
        "block_index": use.block_index,
        "input": bounded_tool_input(use.input, codex_exec=use.name == CODEX_EXEC_TOOL),
    }
    if use.name == BASH_TOOL_NAME:
        parameters["command"] = redact_secret_text(use.input.get("command"), max_chars=MAX_COMMAND_CHARS)
    return parameters


# Rows of one message share created_at, so block_index orders them even when the execution-evidence hook created one
# before its siblings.
async def _upsert_tool_calls(db: AsyncSession, session_id: str, delta: TurnDelta) -> None:
    ids = [use.tool_use_id for use in delta.prior_tool_uses] + [result.tool_use_id for result in delta.tool_results]
    ids = [item[:64] for item in ids if item]
    if not ids:
        return
    rows = (
        await db.execute(select(ToolCall).where(ToolCall.session_id == session_id, ToolCall.request_id.in_(ids)))
    ).scalars()
    existing = {
        row.request_id: row
        for row in rows
        if isinstance(row.parameters, Mapping) and row.parameters.get("source") == TOOL_CALL_SOURCE_GATEWAY
    }
    recorded_at = utc_now()
    for use in delta.prior_tool_uses:
        key = use.tool_use_id[:64]
        if not key:
            continue
        row = existing.get(key)
        if row is None:
            row = ToolCall(
                id=str(uuid.uuid4()),
                session_id=session_id,
                tool_name=use.name[:200] or "unknown",
                parameters=_tool_use_parameters(use),
                result=None,
                status=TOOL_CALL_STATUS_REQUESTED,
                request_id=key,
                created_at=recorded_at,
            )
            db.add(row)
            existing[key] = row
        elif "block_index" not in row.parameters:
            row.parameters = {**row.parameters, **_tool_use_parameters(use)}
            row.tool_name = use.name[:200] or row.tool_name
            row.created_at = recorded_at
    for result in delta.tool_results:
        row = existing.get(result.tool_use_id[:64])
        if row is None:
            continue
        row.result = {
            "is_error": result.is_error,
            "excerpt": result_excerpt(result.text),
        }
        row.status = TOOL_CALL_STATUS_ERROR if result.is_error else TOOL_CALL_STATUS_SUCCESS


__all__ = [
    "bounded_tool_input",
    "result_excerpt",
    "upsert_gateway_tool_calls",
]


# Shared with the seat route (``seat_transcript.py``).
upsert_gateway_tool_calls = _upsert_tool_calls
