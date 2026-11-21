"""Call history and call-debug log readers for the call monitoring panel."""

from __future__ import annotations

import subprocess
from typing import Any

from sqlalchemy import String, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.error_facts import error_text
from app.services.process_output_redaction import redact_process_output

_CALL_LOG_FILE = "/tmp/uvicorn.log"
_CALL_DEBUG_PATTERN = (
    r"CALL DEBUG|enrollment|enroll|playPrompt|recordResponse|STT result|"
    r"Recording completed|Recording failed|bot speaking|playback|Waiting|"
    r"terminated|established|Wake word"
)


def _grep_call_log(call_id: str | None) -> subprocess.CompletedProcess:
    if call_id and call_id.strip():
        # Filter by specific call_id — get ALL lines mentioning this call
        return subprocess.run(
            ["grep", "-F", call_id.strip(), _CALL_LOG_FILE],
            capture_output=True,
            text=True,
            timeout=10,
        )
    # General call debug filter
    return subprocess.run(
        [
            "grep",
            "-i",
            "-E",
            _CALL_DEBUG_PATTERN,
            _CALL_LOG_FILE,
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )


def read_call_log_lines(call_id: str | None, bounded_limit: int) -> list[str]:
    """The last call-debug lines of the uvicorn log, redacted; a single explanatory line when it cannot be read."""
    try:
        result = _grep_call_log(call_id)
        # The matched log lines are what the admin call-debug view shows: kept, redacted.
        output = redact_process_output(result.stdout).strip()
        lines = output.split("\n") if output else []
        # Return last N lines
        return lines[-bounded_limit:]
    except FileNotFoundError:
        return ["Log file not found: /tmp/uvicorn.log"]
    except subprocess.TimeoutExpired:
        return ["Log read timed out"]
    except Exception as e:
        return [f"Error reading log: {error_text('call_log_read_failed', e)}"]


def _history_query(session_model: Any, search_term: str, bounded_limit: int) -> Any:
    query = (
        select(session_model)
        .where(session_model.agent_type == "teams_call")
        .order_by(session_model.started_at.desc())
        .limit(bounded_limit)
    )
    if not search_term:
        return query
    # Search in metadata JSON (call_id, caller name) and session id
    return (
        select(session_model)
        .where(session_model.agent_type == "teams_call")
        .where(
            (func.lower(session_model.id).contains(search_term))
            | (func.lower(func.json_extract(session_model.metadata_, "$.call_id")).contains(search_term))
            | (
                func.lower(func.json_extract(session_model.metadata_, "$.caller_display_name")).contains(
                    search_term
                )
            )
            | (func.cast(session_model.started_at, String).contains(search_term))
        )
        .order_by(session_model.started_at.desc())
        .limit(bounded_limit)
    )


def _stored_call_info(sess: Any, call_states: dict) -> dict | None:
    meta = dict(sess.metadata_ or {})
    call_id = meta.get("call_id", "")
    if not call_id:
        return None
    state = call_states.get(call_id)
    info = {
        "call_id": call_id,
        "is_active": state is not None,
        "caller_name": meta.get("caller_display_name", ""),
        "started_at": sess.started_at.isoformat() if sess.started_at else None,
        "ended_at": sess.ended_at.isoformat() if sess.ended_at else None,
        "db_session_id": sess.id,
        "segments": meta.get("transcript_segments", 0),
        "status": sess.status or "unknown",
    }
    # If still live, get fresher data from memory
    if state:
        info["segments"] = len(state.segments)
        info["caller_name"] = getattr(state, "caller_display_name", "") or info["caller_name"]
    return info


def _live_call_matches(call_id: str, state: Any, search_term: str) -> bool:
    if not search_term:
        return True
    searchable_parts = [
        call_id,
        getattr(state, "caller_display_name", ""),
        state.db_session_id or "",
        state.started_at.isoformat() if state.started_at else "",
    ]
    searchable = " ".join(searchable_parts).lower()
    return search_term in searchable


def _live_call_info(call_id: str, state: Any) -> dict:
    return {
        "call_id": call_id,
        "is_active": True,
        "caller_name": getattr(state, "caller_display_name", "") or "",
        "started_at": state.started_at.isoformat() if state.started_at else None,
        "ended_at": None,
        "db_session_id": state.db_session_id,
        "segments": len(state.segments),
        "status": "active",
    }


async def load_call_history(
    db: AsyncSession,
    *,
    session_model: Any,
    call_states: dict,
    search_term: str,
    bounded_limit: int,
) -> list[dict]:
    """Recent stored calls plus live calls that have no stored session yet, newest live calls first."""
    calls_info: list[dict] = []
    result = await db.execute(_history_query(session_model, search_term, bounded_limit))
    for sess in result.scalars().all():
        info = _stored_call_info(sess, call_states)
        if info is not None:
            calls_info.append(info)

    # Also add live calls that might not have a DB session yet
    for call_id, state in call_states.items():
        already_listed = any(c["call_id"] == call_id for c in calls_info)
        if not already_listed and _live_call_matches(call_id, state, search_term):
            calls_info.insert(0, _live_call_info(call_id, state))
    return calls_info
