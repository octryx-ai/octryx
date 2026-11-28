"""Codex code mode: a hook-reported inner call of an ``exec`` counts as gateway evidence when the gateway
recorded the same literal call in an ``exec`` input of the same session."""

from __future__ import annotations

import re
from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ...models import ToolCall
from .codex_exec_keys import EXEC_CALL_KEY, _Call, _hook_key, _occurrence_call, _parameters, _slot_matches
from .codex_exec_parser import exec_occurrences
from .contract import (
    EXECUTION_OUTCOME_FAILED,
    EXECUTION_OUTCOME_SUCCEEDED,
    TOOL_CALL_EXECUTED_KEY,
    TOOL_CALL_SOURCE_GATEWAY,
    TOOL_CALL_SOURCE_HOOK,
    TOOL_CALL_STATUS_ERROR,
    TOOL_CALL_STATUS_SUCCESS,
)
from .engine_keys import ENGINE_CODEX, SESSION_ENGINE_KEY
from .stored_types import ExecCallRecord

EXEC_TOOL = "exec"
EXEC_ID_PREFIX = "exec-"
EXEC_MATCH_KEY = "exec_match"
# The gateway write that ends a response may land a moment after Codex already started running its exec.
EMIT_SKEW = timedelta(seconds=5)
LITERAL_HINT = ("Some of your calls inside exec could not be counted as evidence: their arguments were not literal "
                "(a variable, ${} interpolation, a loop or a computed name). Call read/test commands with a literal "
                "command string (tools.exec_command({cmd:\"cat README.md\"})), one call per command; pass a patch as "
                "a string literal or a const bound to one "
                "(const patch = \"*** Begin Patch…\"; tools.apply_patch(patch)).")
_EXIT_CODE = re.compile(r'"exit_code"\s*:\s*(-?\d+)')


def is_codex_session(session: Any) -> bool:
    metadata = getattr(session, "metadata_", None)
    return isinstance(metadata, Mapping) and metadata.get(SESSION_ENGINE_KEY) == ENGINE_CODEX


def is_exec_inner_id(tool_use_id: Any) -> bool:
    return isinstance(tool_use_id, str) and tool_use_id.startswith(EXEC_ID_PREFIX)


def exec_call_record(tool_name: str, hook_input: Mapping[str, Any]) -> ExecCallRecord:
    # Bounded and redacted like the gateway's own tool input.
    from ..model_gateway.inbound.transcript_tools import bounded_tool_input

    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), Mapping) else {}
    return {"tool": tool_name, "input": bounded_tool_input(tool_input), "cwd": str(hook_input.get("cwd") or "")[:500]}



def _recorded(row: ToolCall) -> bool:
    return _parameters(row).get("source") == TOOL_CALL_SOURCE_GATEWAY and type(
        _parameters(row).get("block_index")) is int


def _exec_script(row: ToolCall) -> str | None:
    if row.tool_name != EXEC_TOOL or not _recorded(row):
        return None
    tool_input = _parameters(row).get("input")
    script = tool_input.get("input") if isinstance(tool_input, Mapping) else None
    return script if isinstance(script, str) else None


def _inner_hook_row(row: ToolCall) -> bool:
    parameters = _parameters(row)
    executed = parameters.get(TOOL_CALL_EXECUTED_KEY)
    return (is_exec_inner_id(row.request_id or parameters.get("tool_use_id"))
            and parameters.get("source") == TOOL_CALL_SOURCE_GATEWAY
            and "block_index" not in parameters
            and isinstance(executed, Mapping) and executed.get("source") == TOOL_CALL_SOURCE_HOOK
            and executed.get("outcome") in (EXECUTION_OUTCOME_SUCCEEDED, EXECUTION_OUTCOME_FAILED))


def _emitted_after(row: ToolCall, writes: Mapping[str, list[datetime]]) -> datetime:
    # An exec row is written with the next request; the response that emitted it ended at the previous write.
    times = writes.get(str(row.session_id), [])
    index = bisect_left(times, row.created_at or datetime.min)
    return times[index - 1] - EMIT_SKEW if index > 0 else datetime.min


@dataclass(slots=True)
class _Slot:
    row: ToolCall
    occurrence: int
    call: _Call | None
    after: datetime
    used: bool = False


@dataclass(frozen=True, slots=True)
class ExecEvidence:
    rows: list[ToolCall]
    matched: tuple[str, ...]
    unmatched: tuple[ToolCall, ...]


def _excerpt(row: ToolCall) -> str:
    result = row.result if isinstance(row.result, Mapping) else {}
    return str(result.get("excerpt") or "")


def _exec_green(exec_row: ToolCall) -> bool:
    result = exec_row.result if isinstance(exec_row.result, Mapping) else None
    if exec_row.status != TOOL_CALL_STATUS_SUCCESS or result is None or result.get("is_error") is not False:
        return False
    text = _excerpt(exec_row)
    return not text.lstrip().startswith("Script failed") and all(code == "0" for code in _EXIT_CODE.findall(text))


def _matched_row(hook: ToolCall, slot: _Slot) -> ToolCall:
    # A transient copy: never added to the session.
    parameters = dict(_parameters(hook))
    executed = parameters.get(TOOL_CALL_EXECUTED_KEY) if isinstance(parameters.get(TOOL_CALL_EXECUTED_KEY),
                                                                   Mapping) else {}
    call = slot.call
    reported = parameters.get(EXEC_CALL_KEY) if isinstance(parameters.get(EXEC_CALL_KEY), Mapping) else {}
    hook_input = reported.get("input") if isinstance(reported.get("input"), Mapping) else {}
    parameters.update({"block_index": _parameters(slot.row).get("block_index"), "input": dict(hook_input),
                       EXEC_MATCH_KEY: {"exec_tool_use_id": slot.row.request_id, "occurrence": slot.occurrence}})
    if call is not None and call.tool == "Bash":
        parameters["command"] = call.command
    succeeded = executed.get("outcome") == EXECUTION_OUTCOME_SUCCEEDED
    if succeeded and call is not None and call.tool == "Bash":
        succeeded = _exec_green(slot.row)  # a shell call's own exit status lives only in the exec's output
    return ToolCall(id=hook.id, session_id=hook.session_id, message_id=hook.message_id, tool_name=hook.tool_name,
                    parameters=parameters, status=TOOL_CALL_STATUS_SUCCESS if succeeded else TOOL_CALL_STATUS_ERROR,
                    result={"is_error": not succeeded, "excerpt": _excerpt(slot.row)},
                    duration_ms=hook.duration_ms, request_id=hook.request_id, created_at=hook.created_at)


def match_exec_calls(rows: Sequence[ToolCall]) -> ExecEvidence:
    recorded = [row for row in rows if _recorded(row)]
    writes: dict[str, list[datetime]] = {}
    for row in recorded:
        if row.created_at is not None:
            writes.setdefault(str(row.session_id), []).append(row.created_at)
    for times in writes.values():
        times.sort()
    slots: list[_Slot] = []
    for row in sorted(recorded, key=lambda item: (item.created_at or datetime.min,
                                                  _parameters(item).get("block_index") or 0)):
        script = _exec_script(row)
        if script is None:
            continue
        occurrences = exec_occurrences(script)
        after = _emitted_after(row, writes)
        for index, occurrence in enumerate(occurrences):
            call = _occurrence_call(occurrence) if occurrence.literal else None
            slots.append(_Slot(row, index, call, after))
    replaced: dict[int, ToolCall] = {}
    unmatched: list[ToolCall] = []
    # Newest report first: it belongs to the most recent exec asked for before it, so an older report never takes
    # the occurrence of a later exec.
    hooks = sorted((row for row in rows if _inner_hook_row(row)), key=lambda item: item.created_at or datetime.min,
                   reverse=True)
    for hook in hooks:
        reported = hook.created_at or datetime.min
        key = _hook_key(hook)
        eligible = [slot for slot in slots
                    if key is not None and not slot.used and slot.call is not None
                    and slot.row.session_id == hook.session_id and slot.after < reported
                    and _slot_matches(slot.call, key)]
        if not eligible:
            unmatched.append(hook)
            continue
        newest = max(slot.after for slot in eligible)  # the most recent exec the model asked for before the report
        slot = next(slot for slot in eligible if slot.after == newest)
        slot.used = True
        replaced[id(hook)] = _matched_row(hook, slot)
    out = [replaced.get(id(row), row) for row in rows]
    return ExecEvidence(out, tuple(str(replaced[key].request_id or "") for key in replaced), tuple(reversed(unmatched)))


def codex_exec_evidence(session: Any, rows: Sequence[ToolCall]) -> ExecEvidence | None:
    if not is_codex_session(session):
        return None
    return match_exec_calls(rows)


def with_literal_hint(answer: dict[str, Any], evidence: ExecEvidence | None) -> dict[str, Any]:
    # Only inner calls left unmatched since the last matched one earn the hint.
    if evidence is None or not evidence.unmatched or answer.get("state") != "blocked":
        return answer
    matched_at = [row.created_at for row in evidence.rows
                  if isinstance(row.parameters, dict) and EXEC_MATCH_KEY in row.parameters and row.created_at]
    newest = max(matched_at) if matched_at else None
    if newest is not None and all((row.created_at or datetime.min) < newest for row in evidence.unmatched):
        return answer
    detail = str(answer.get("detail") or "").strip()
    return {**answer, "detail": f"{detail} {LITERAL_HINT}".strip()}


__all__ = [
    "EXEC_ID_PREFIX",
    "EXEC_MATCH_KEY",
    "ExecEvidence",
    "LITERAL_HINT",
    "codex_exec_evidence",
    "exec_call_record",
    "is_codex_session",
    "is_exec_inner_id",
    "match_exec_calls",
    "with_literal_hint",
]
