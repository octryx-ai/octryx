"""Service-owned chat turn completion state transitions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message
from ...models import Session as AgentSession
from .completion_quality import (
    latest_failed_test_validation_summary,
    unverified_verification_contract_summary,
)
from .run_state import (
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_AWAITING_SUBAGENTS,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_STOPPED,
    infer_completion_reason_from_content,
    set_session_run_state,
)
from .turn_approval_state import end_chat_turn

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ChatTurnCompletionResult:
    session_id: str
    session_status: str
    run_status: str
    run_completion_reason: str
    project_id: str | None = None
    agent_type: str | None = None
    latest_assistant_message_id: str | None = None
    latest_assistant_content: str | None = None
    completion_follow_up: dict[str, Any] | None = None


def parse_metadata_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed.replace(tzinfo=None)


async def finalize_chat_turn_after_agent_stream(
    db: AsyncSession,
    *,
    session_id: str,
) -> ChatTurnCompletionResult:
    session = await db.get(AgentSession, session_id)
    if session is None:
        return ChatTurnCompletionResult(
            session_id=session_id,
            session_status="missing",
            run_status=RUN_STATUS_COMPLETED,
            run_completion_reason="completed",
        )

    metadata = dict(session.metadata_ or {})
    sub_agent_resume_group_id = str(metadata.get("sub_agent_resume_started_group_id") or "").strip()
    if session.status == "awaiting_subagents" and sub_agent_resume_group_id:
        session.status = "active"
        metadata.pop("current_sub_agent_group_id", None)
        metadata.pop("sub_agent_group_child_session_ids", None)
        metadata.pop("sub_agent_resume_started_group_id", None)
    elif session.status not in {"archived", "pending_approval", "awaiting_subagents", "active"}:
        session.status = "active"

    current_turn_started_at = parse_metadata_datetime(metadata.get("current_turn_started_at"))
    # A turn paused at an approval stays resumable through its approval binding.
    end_chat_turn(metadata)
    metadata.pop("resume_state", None)
    if session.status not in {"pending_approval", "awaiting_subagents", "active"}:
        metadata.pop("run_started_at", None)
    session.metadata_ = metadata

    if session.status == "pending_approval":
        set_session_run_state(session, RUN_STATUS_AWAITING_APPROVAL, "approval_required")
        return _completion_result(session, run_status=RUN_STATUS_AWAITING_APPROVAL, reason="approval_required")

    if session.status == "awaiting_subagents":
        set_session_run_state(session, RUN_STATUS_AWAITING_SUBAGENTS, "waiting_for_sub_agents")
        return _completion_result(
            session,
            run_status=RUN_STATUS_AWAITING_SUBAGENTS,
            reason="waiting_for_sub_agents",
        )

    latest_assistant = await _latest_assistant_message(db, session_id=session_id)
    validation_failure = await latest_failed_test_validation_summary(
        db,
        session_id=session_id,
        created_at_or_after=current_turn_started_at,
    )
    if validation_failure:
        metadata["completion_blocker"] = {
            "reason": "latest_test_validation_failed",
            **validation_failure,
        }
        session.metadata_ = metadata
        set_session_run_state(session, RUN_STATUS_FAILED, "validation_failed")
        await _sync_coding_pipeline(
            db, session_id=session_id, run_status=RUN_STATUS_FAILED, reason="validation_failed"
        )
        return _completion_result(
            session,
            run_status=RUN_STATUS_FAILED,
            reason="validation_failed",
            latest_assistant=latest_assistant,
        )

    contract_blocker = await unverified_verification_contract_summary(
        db,
        session_id=session_id,
        session_metadata=metadata,
        created_at_or_after=current_turn_started_at,
    )
    if contract_blocker:
        metadata["completion_blocker"] = contract_blocker
        session.metadata_ = metadata
        set_session_run_state(session, RUN_STATUS_FAILED, contract_blocker["reason"])
        await _sync_coding_pipeline(
            db, session_id=session_id, run_status=RUN_STATUS_FAILED, reason=contract_blocker["reason"]
        )
        return _completion_result(
            session,
            run_status=RUN_STATUS_FAILED,
            reason=contract_blocker["reason"],
            latest_assistant=latest_assistant,
        )

    metadata.pop("completion_blocker", None)
    session.metadata_ = metadata
    completion_reason = infer_completion_reason_from_content(latest_assistant.content if latest_assistant else "")
    run_status = RUN_STATUS_STOPPED if completion_reason == "agent_stopped" else RUN_STATUS_COMPLETED
    set_session_run_state(session, run_status, completion_reason)
    if run_status == RUN_STATUS_STOPPED:
        await _sync_coding_pipeline(db, session_id=session_id, run_status=run_status, reason=completion_reason)
    follow_up = None
    if run_status == RUN_STATUS_COMPLETED:
        follow_up = _completion_follow_up_payload(session, latest_assistant, completion_reason=completion_reason)
    return _completion_result(
        session,
        run_status=run_status,
        reason=completion_reason,
        latest_assistant=latest_assistant,
        completion_follow_up=follow_up,
    )


async def _sync_coding_pipeline(
    db: AsyncSession, *, session_id: str, run_status: str, reason: str | None
) -> None:
    try:  # a late import: secure_work depends on the session services
        from ..secure_work.coding.coding_pipeline_session_sync import fail_pipeline_runs_for_session

        await fail_pipeline_runs_for_session(
            db, session_id=session_id, run_status=run_status, reason=reason
        )
    except Exception:  # noqa: BLE001 - pipeline sync must not break turn completion
        logger.exception("coding_pipeline_session_sync_failed", extra={"session_id": session_id})


async def _latest_assistant_message(db: AsyncSession, *, session_id: str) -> Message | None:
    return (
        (
            await db.execute(
                select(Message)
                .where(Message.session_id == session_id, Message.role == "assistant")
                .order_by(Message.created_at.desc())
            )
        )
        .scalars()
        .first()
    )


def _completion_follow_up_payload(
    session: AgentSession,
    latest_assistant: Message | None,
    *,
    completion_reason: str,
) -> dict[str, Any]:
    return {
        "session_id": session.id,
        "project_id": session.project_id,
        "agent_type": session.agent_type,
        "latest_assistant_message_id": latest_assistant.id if latest_assistant else None,
        "latest_assistant_content": latest_assistant.content if latest_assistant else None,
        "completion_reason": completion_reason,
    }


def _completion_result(
    session: AgentSession,
    *,
    run_status: str,
    reason: str,
    latest_assistant: Message | None = None,
    completion_follow_up: dict[str, Any] | None = None,
) -> ChatTurnCompletionResult:
    return ChatTurnCompletionResult(
        session_id=session.id,
        session_status=str(session.status or ""),
        run_status=run_status,
        run_completion_reason=reason,
        project_id=session.project_id,
        agent_type=session.agent_type,
        latest_assistant_message_id=latest_assistant.id if latest_assistant else None,
        latest_assistant_content=latest_assistant.content if latest_assistant else None,
        completion_follow_up=completion_follow_up,
    )


__all__ = [
    "ChatTurnCompletionResult",
    "finalize_chat_turn_after_agent_stream",
    "parse_metadata_datetime",
]
