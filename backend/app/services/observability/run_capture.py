"""What a run stores: one capture policy per Workspace, applied to ``turn_traces`` at storage.

The Workspace setting ``trace_capture.mode`` (Workspace settings → Observability; platform default ``standard``)
governs the store that holds run content:

- ``minimal``: no content is stored, only the run's metadata (model, tokens, outcome, the gate that stopped it);
- ``standard`` / ``debug`` / ``audit``: content is stored within the runtime trace limits.

In every mode secrets are redacted before the row is written (not at display). The keys the run summary, the
decision record and the effective setup read are always kept. The first write applies the policy in
``persist_turn_trace``; every later write of a content column (the tool batch and tool follow-up rewrite the tool
trace and the context after the tools ran) passes the ``before_flush`` listener below, so no writer can bypass it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as OrmSession

from ...models import Project, Session, TurnTrace
from ..redaction_policy import redact_secret_payload

MODE_MINIMAL = "minimal"
DEFAULT_MODE = "standard"
METADATA_ONLY = {"capture": "metadata_only", "reason": "minimal_mode"}
# Kept in every mode: what Runs, Decisions and the drawer read (all bounded and already free of content).
_KEPT_OUTPUT_KEYS = ("gate_outcome", "status", "end_reason", "stop_reason", "runtime_attempts", "error_class")
_KEPT_CONTEXT_KEYS = ("request_id", "source", "agent", "execution_profile", "turn_execution_snapshot",
                      "answer_evidence", "job_id", "profile", "claude_session_id")


_CONTENT_COLUMNS = ("input_messages_json", "context_snapshot_json", "tool_trace_json", "raw_output")
# The mode the first write applied, remembered on the instance so a later write in the same unit of work needs no
# lookup. A row loaded from the database has none; the listener then reads the Workspace setting.
_MODE_ATTRIBUTE = "_octryx_capture_mode"


def _mode_of(project: Project | None) -> str:
    config = project.config if project is not None and isinstance(project.config, Mapping) else {}
    capture = config.get("trace_capture")
    mode = str(capture.get("mode") or "").strip() if isinstance(capture, Mapping) else ""
    return mode or DEFAULT_MODE


async def capture_mode(db: AsyncSession, session_id: str) -> str:
    session = await db.get(Session, session_id)
    return _mode_of(await db.get(Project, session.project_id) if session is not None and session.project_id else None)


def remember_capture_mode(trace: TurnTrace, mode: str) -> None:
    setattr(trace, _MODE_ATTRIBUTE, mode)


def _kept(payload: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    source = payload if isinstance(payload, Mapping) else {}
    return {key: source[key] for key in keys if key in source}


def captured(
    mode: str, *, input_messages: Any, context_snapshot: Any, tool_trace: Any, raw_output: Any,
) -> tuple[Any, Any, Any, Any]:
    """The four payloads as stored under ``mode``: redacted, or reduced to metadata for ``minimal``."""
    if mode == MODE_MINIMAL:
        error = raw_output.get("error") if isinstance(raw_output, Mapping) else None
        output = {**METADATA_ONLY, **_kept(raw_output, _KEPT_OUTPUT_KEYS), **({"error": True} if error else {})}
        return [], {**METADATA_ONLY, **_kept(context_snapshot, _KEPT_CONTEXT_KEYS)}, [], output
    return (
        redact_secret_payload(input_messages),
        redact_secret_payload(context_snapshot),
        redact_secret_payload(tool_trace),
        redact_secret_payload(raw_output),
    )


def _stored_mode(session: OrmSession, trace: TurnTrace) -> str:
    mode = getattr(trace, _MODE_ATTRIBUTE, None)
    if mode:
        return mode
    with session.no_autoflush:
        chat = session.get(Session, trace.session_id)
        project = session.get(Project, chat.project_id) if chat is not None and chat.project_id else None
    mode = _mode_of(project)
    remember_capture_mode(trace, mode)
    return mode


@event.listens_for(OrmSession, "before_flush")
def _capture_later_writes(session: OrmSession, _flush_context: Any, _instances: Any) -> None:
    """Apply the capture policy to every later write of a stored run's content columns."""
    for trace in [item for item in session.dirty if isinstance(item, TurnTrace)]:
        state = inspect(trace)
        changed = [column for column in _CONTENT_COLUMNS if state.attrs[column].history.has_changes()]
        if not changed:
            continue
        stored = dict(zip(_CONTENT_COLUMNS, captured(
            _stored_mode(session, trace), input_messages=trace.input_messages_json,
            context_snapshot=trace.context_snapshot_json, tool_trace=trace.tool_trace_json,
            raw_output=trace.raw_output,
        ), strict=True))
        for column in changed:
            setattr(trace, column, stored[column])


def gateway_capture(mode: str, *, input_messages: Any, context_snapshot: Any, raw_output: Any) -> dict[str, Any]:
    """``TurnTrace`` keyword arguments for a model-gateway call under ``mode``."""
    stored_input, stored_context, _tools, stored_output = captured(
        mode, input_messages=input_messages, context_snapshot=context_snapshot, tool_trace=[], raw_output=raw_output
    )
    return {"input_messages_json": stored_input, "context_snapshot_json": stored_context, "raw_output": stored_output}


__all__ = ["MODE_MINIMAL", "capture_mode", "captured", "gateway_capture", "remember_capture_mode"]
