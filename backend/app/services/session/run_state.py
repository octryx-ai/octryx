"""Helpers for explicit per-request run state on reusable chat sessions."""

from __future__ import annotations

import re
from typing import Any

from .shared import get_session_metadata, set_session_metadata_value
from .turn_owner import claim_turn_ownership

RUN_STATUS_IN_PROGRESS = "in_progress"
RUN_STATUS_AWAITING_APPROVAL = "awaiting_approval"
RUN_STATUS_AWAITING_SUBAGENTS = "awaiting_subagents"
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_STOPPED = "stopped"

RUN_STATUS_METADATA_KEY = "run_status"
RUN_COMPLETION_REASON_METADATA_KEY = "run_completion_reason"


def get_session_run_status(session: Any) -> str:
    metadata = get_session_metadata(session)
    return str(metadata.get(RUN_STATUS_METADATA_KEY) or "").strip().lower()


def get_session_run_completion_reason(session: Any) -> str:
    metadata = get_session_metadata(session)
    return str(metadata.get(RUN_COMPLETION_REASON_METADATA_KEY) or "").strip().lower()


def set_session_run_state(session: Any, run_status: str, completion_reason: str | None = None) -> None:
    normalized_status = str(run_status or "").strip().lower()
    if normalized_status == RUN_STATUS_IN_PROGRESS:
        # Every turn start passes here; this process now owns the running turn.
        claim_turn_ownership(session)
    set_session_metadata_value(session, RUN_STATUS_METADATA_KEY, normalized_status)
    if completion_reason:
        set_session_metadata_value(
            session,
            RUN_COMPLETION_REASON_METADATA_KEY,
            str(completion_reason).strip().lower(),
        )
        return
    set_session_metadata_value(session, RUN_COMPLETION_REASON_METADATA_KEY, None)


def infer_completion_reason_from_content(content: str | None) -> str:
    text = str(content or "").strip().lower()
    if not text:
        return "completed"
    if text.startswith("agent stopped because") or "stalled_on_" in text:
        return "agent_stopped"
    if text.startswith("agent error:") or "synthetic failure" in text:
        return "error"
    if any(
        marker in text
        for marker in (
            "no update is required",
            "no updates are required",
            "no changes are required",
            "no documentation changes",
            "no documentation update",
            "no-op",
            "unchanged",
        )
    ):
        return "no_changes_needed"
    if "approval required" in text:
        return "approval_required"
    if "human input required" in text:
        return "human_input_required"
    if re.search(r"\b(completed|finished|synchronized)\b", text):
        return "completed"
    return "completed"
