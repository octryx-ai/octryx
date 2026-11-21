from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...models import Message, Session, SubAgentGroup, ToolCall, User
from ...models.runtime.product_run import RUN_ORIGIN_SUB_AGENT
from ...time_utils import ensure_utc, utc_now, utc_now_aware
from ..error_facts import error_text
from ..prompt_catalog.out_of_turn import render_prompt_for_scope
from ..session.run_state import RUN_STATUS_COMPLETED, RUN_STATUS_FAILED, set_session_run_state
from ..session.stream import session_stream_manager
from ..session.turn_refusals import TurnRefusal
from ..session.turn_request import TurnRequest
from ..session.turn_tasks import CHAT_RUN_TASKS
from .evidence import (
    determine_sub_agent_evidence_profile,
    summarize_sub_agent_evidence_quality,
)

logger = logging.getLogger(__name__)

SUB_AGENT_GROUP_STATUS_RUNNING = "running"
SUB_AGENT_GROUP_STATUS_COMPLETED = "completed"
SUB_AGENT_GROUP_STATUS_TIMED_OUT = "timed_out"
SUB_AGENT_GROUP_STATUS_RESUMED = "resumed"
MIN_SUB_AGENT_GROUP_TIMEOUT_SECONDS = 30
DEFAULT_SUB_AGENT_GROUP_TIMEOUT_SECONDS = 300
MAX_SUB_AGENT_GROUP_TIMEOUT_SECONDS = 10_800

# Default resume prompts of the parent (catalog keys); a group may carry its own resume prompt.
SUB_AGENT_WAITING_PROMPT_KEY = "research.sub_agent_group.waiting"
SUB_AGENT_TIMEOUT_PROMPT_KEY = "research.sub_agent_group.timeout"

_GROUP_LOCKS: dict[str, asyncio.Lock] = {}
_GROUP_TIMEOUT_TASKS: dict[str, asyncio.Task[Any]] = {}
_GROUP_CHILD_TASKS: dict[str, set[asyncio.Task[Any]]] = {}


def _group_lock(group_id: str) -> asyncio.Lock:
    lock = _GROUP_LOCKS.get(group_id)
    if lock is None:
        lock = asyncio.Lock()
        _GROUP_LOCKS[group_id] = lock
    return lock


def _terminal_child_status(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if not normalized:
        return ""
    if normalized in {"completed", "failed", "timed_out"}:
        return normalized
    if normalized in {"error", "stopped"}:
        return "failed"
    return normalized


async def _group_prompt(db: AsyncSession, parent_session_id: str, key: str) -> str:
    """A default resume prompt, rendered for the parent session's Workspace (no turn may be bound)."""
    parent = await db.get(Session, parent_session_id)
    return await render_prompt_for_scope(db, key, workspace_id=getattr(parent, "project_id", None))


async def _build_group_resume_prompt(db: AsyncSession, group: SubAgentGroup) -> str:
    if group.resume_prompt:
        return str(group.resume_prompt)
    if str(group.status or "").strip().lower() == SUB_AGENT_GROUP_STATUS_TIMED_OUT:
        return await _group_prompt(db, group.parent_session_id, SUB_AGENT_TIMEOUT_PROMPT_KEY)
    return await _group_prompt(db, group.parent_session_id, SUB_AGENT_WAITING_PROMPT_KEY)


def _terminal_status_from_child_session(session: Session | None) -> str:
    if session is None:
        return ""
    normalized_status = str(session.status or "").strip().lower()
    if normalized_status == "completed":
        return "completed"
    if normalized_status == "error":
        return "failed"
    if normalized_status == "stopped":
        metadata = dict(session.metadata_ or {})
        if str(metadata.get("timeout_reason") or "").strip() == "sub_agent_group_timeout":
            return "timed_out"
        return "failed"
    return ""


def normalize_sub_agent_group_timeout_seconds(
    value: Any,
    *,
    default: int = DEFAULT_SUB_AGENT_GROUP_TIMEOUT_SECONDS,
) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        resolved = default
    return max(
        MIN_SUB_AGENT_GROUP_TIMEOUT_SECONDS,
        min(resolved, MAX_SUB_AGENT_GROUP_TIMEOUT_SECONDS),
    )


async def _reconcile_group_progress(db: AsyncSession, group: SubAgentGroup) -> bool:
    child_session_ids = [str(item).strip() for item in (group.child_session_ids_json or []) if str(item).strip()]
    child_statuses = {
        child_session_id: _terminal_child_status((group.child_statuses_json or {}).get(child_session_id, ""))
        for child_session_id in child_session_ids
    }
    child_sessions_by_id: dict[str, Session] = {}
    if child_session_ids:
        child_sessions = (
            await db.execute(select(Session).where(Session.id.in_(child_session_ids)))
        ).scalars().all()
        child_sessions_by_id = {session.id: session for session in child_sessions}
    for child_session_id in child_session_ids:
        if child_statuses.get(child_session_id) in {"completed", "failed", "timed_out"}:
            continue
        fallback_status = _terminal_status_from_child_session(child_sessions_by_id.get(child_session_id))
        if fallback_status:
            child_statuses[child_session_id] = fallback_status
    group.child_statuses_json = child_statuses
    group.completed_count = sum(1 for value in child_statuses.values() if value == "completed")
    group.failed_count = sum(1 for value in child_statuses.values() if value in {"failed", "timed_out"})
    return len(
        [child_session_id for child_session_id in child_session_ids if child_statuses.get(child_session_id)]
    ) >= len(child_session_ids)


def _release_group_lock(group_id: str) -> None:
    """Remove the lock for a completed group so it doesn't accumulate in memory."""
    _GROUP_LOCKS.pop(group_id, None)


async def create_sub_agent_group(
    db: AsyncSession,
    *,
    parent_session_id: str,
    child_session_ids: list[str],
    timeout_seconds: int = DEFAULT_SUB_AGENT_GROUP_TIMEOUT_SECONDS,
    resume_prompt: str | None = None,
) -> SubAgentGroup:
    safe_timeout = normalize_sub_agent_group_timeout_seconds(timeout_seconds)
    group = SubAgentGroup(
        parent_session_id=parent_session_id,
        status=SUB_AGENT_GROUP_STATUS_RUNNING,
        total_count=len(child_session_ids),
        child_session_ids_json=list(child_session_ids),
        child_statuses_json={},
        timeout_at=utc_now() + timedelta(seconds=safe_timeout),
        resume_prompt=resume_prompt or await _group_prompt(db, parent_session_id, SUB_AGENT_WAITING_PROMPT_KEY),
    )
    db.add(group)
    await db.flush()
    return group


async def launch_sub_agent_group(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    group_id: str,
    parent_session_id: str,
    user_id: str,
    project_id: str | None,
    agent_type: str,
    runtime_target_id: str | None,
    thinking_level: str | None,
    agent_definition: dict[str, Any] | None,
    sub_agent_depth: int,
    child_runs: list[dict[str, str]],
    max_concurrent_children: int | None = None,
) -> None:
    child_tasks: set[asyncio.Task[Any]] = set()
    child_limit = max(1, int(max_concurrent_children or len(child_runs) or 1))
    semaphore = asyncio.Semaphore(child_limit)

    def _on_child_task_done(done_task: asyncio.Task[Any], *, child_group_id: str) -> None:
        group_tasks = _GROUP_CHILD_TASKS.get(child_group_id)
        if group_tasks is not None:
            group_tasks.discard(done_task)
            if not group_tasks:
                _GROUP_CHILD_TASKS.pop(child_group_id, None)
        if done_task.cancelled():
            logger.info("Sub-agent child task cancelled", extra={"group_id": child_group_id})
            return
        exc = done_task.exception()
        if exc is not None:
            logger.exception("Sub-agent child task crashed", exc_info=exc, extra={"group_id": child_group_id})

    for child_run in child_runs:
        async def _run_limited_child_session(
            *,
            child_session_id: str,
            child_task_text: str,
        ) -> None:
            child_started = False
            try:
                async with semaphore:
                    child_started = True
                    await _run_child_session(
                        session_factory=session_factory,
                        group_id=group_id,
                        parent_session_id=parent_session_id,
                        session_id=child_session_id,
                        task=child_task_text,
                        user_id=user_id,
                        project_id=project_id,
                        agent_type=agent_type,
                        runtime_target_id=runtime_target_id,
                        thinking_level=thinking_level,
                        agent_definition=agent_definition,
                        sub_agent_depth=sub_agent_depth,
                    )
            except asyncio.CancelledError as exc:
                if not child_started:
                    await _mark_child_session_cancelled(
                        session_factory=session_factory,
                        group_id=group_id,
                        session_id=child_session_id,
                        cancel_reason=str(exc) or "sub_agent_cancelled",
                    )
                raise

        child_task = asyncio.create_task(
            _run_limited_child_session(
                child_session_id=child_run["session_id"],
                child_task_text=child_run["task"],
            )
        )
        child_task.add_done_callback(
            lambda done_task, child_group_id=group_id: _on_child_task_done(
                done_task,
                child_group_id=child_group_id,
            )
        )
        child_tasks.add(child_task)
    if child_tasks:
        _GROUP_CHILD_TASKS[group_id] = child_tasks
    timeout_task = asyncio.create_task(
        _watch_sub_agent_group_timeout(
            session_factory=session_factory,
            group_id=group_id,
        )
    )
    _GROUP_TIMEOUT_TASKS[group_id] = timeout_task


async def wait_for_sub_agent_group_tasks_for_parent(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    parent_session_id: str,
    timeout_seconds: float = 5.0,
    cancel_pending: bool = False,
    cancel_reason: str = "validation_timeout",
) -> dict[str, Any]:
    """Wait briefly for in-process child tasks during ASGI-backed validation runs."""

    async with session_factory() as db:
        group_ids = list(
            (
                await db.execute(
                    select(SubAgentGroup.id).where(SubAgentGroup.parent_session_id == parent_session_id)
                )
            ).scalars()
        )

    pending_tasks: set[asyncio.Task[Any]] = set()
    for group_id in group_ids:
        pending_tasks.update(task for task in _GROUP_CHILD_TASKS.get(str(group_id), set()) if not task.done())

    if not pending_tasks:
        return {
            "group_count": len(group_ids),
            "pending_task_count": 0,
            "completed": True,
            "timed_out": False,
        }

    timeout = max(0.1, float(timeout_seconds or 5.0))
    done, pending = await asyncio.wait(pending_tasks, timeout=timeout)
    for task in done:
        if task.cancelled():
            continue
        try:
            task.exception()
        except Exception:
            logger.exception("Sub-agent child task failed while draining validation run")
    cancelled_count = 0
    if pending and cancel_pending:
        for task in pending:
            task.cancel(cancel_reason)
        cancellation_done, pending = await asyncio.wait(pending, timeout=max(2.0, min(10.0, timeout)))
        cancelled_count = sum(1 for task in cancellation_done if task.cancelled())
        for task in cancellation_done:
            if task.cancelled():
                continue
            try:
                task.exception()
            except Exception:
                logger.exception("Sub-agent child task failed while cancelling validation run")
    return {
        "group_count": len(group_ids),
        "pending_task_count": len(pending),
        "completed": not pending,
        "timed_out": bool(pending),
        "cancelled_task_count": cancelled_count,
    }


async def _run_child_session(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    group_id: str,
    parent_session_id: str,
    session_id: str,
    task: str,
    user_id: str,
    project_id: str | None,
    agent_type: str,
    runtime_target_id: str | None,
    thinking_level: str | None,
    agent_definition: dict[str, Any] | None,
    sub_agent_depth: int,
) -> None:
    final_content = ""
    model_name = ""
    try:
        from ...agent.engine import run_agent

        async with session_factory() as db:
            async for event in run_agent(
                session_id=session_id,
                user_message=task,
                user_id=user_id,
                project_id=project_id,
                agent_type=agent_type,
                db=db,
                runtime_target_id=runtime_target_id,
                thinking_level=thinking_level,
                agent_definition=agent_definition,
                parent_session_id=parent_session_id,
                sub_agent_depth=sub_agent_depth,
                run_origin=RUN_ORIGIN_SUB_AGENT,
            ):
                if event.role == "assistant" and event.content:
                    final_content = str(event.content or "")
                    model_name = str(getattr(event, "model", "") or model_name)
                    await session_stream_manager.publish(
                        session_id,
                        "agent_message",
                        {
                            "role": "assistant",
                            "content": final_content,
                            "model": model_name,
                        },
                    )
                elif event.role == "tool":
                    await session_stream_manager.publish(
                        session_id,
                        "tool_call",
                        {
                            "role": "tool",
                            "content": str(getattr(event, "content", "") or ""),
                        },
                    )

            child_session = await db.get(Session, session_id)
            parent_session = await db.get(Session, parent_session_id) if parent_session_id else None
            parent_metadata = dict(parent_session.metadata_ or {}) if parent_session is not None else {}
            workflow_contract_payload = parent_metadata.get("workflow_contract")
            workflow_contract = workflow_contract_payload if isinstance(workflow_contract_payload, dict) else {}
            session_tool_calls = (
                await db.execute(
                    select(ToolCall).where(ToolCall.session_id == session_id).order_by(ToolCall.created_at.asc())
                )
            ).scalars().all()
            evidence_quality = summarize_sub_agent_evidence_quality(
                profile=determine_sub_agent_evidence_profile(parent_session),
                topic=str(workflow_contract.get("topic") or ""),
                status="completed",
                final_response=final_content,
                tool_calls=session_tool_calls,
            )
            child_status = "completed"
            run_status = RUN_STATUS_COMPLETED
            run_completion_reason = "sub_agents_completed"
            run_error = None
            if child_session is not None:
                child_session.ended_at = utc_now()
                metadata = dict(child_session.metadata_ or {})
                metadata.pop("current_turn_user_message_id", None)
                metadata["sub_agent_evidence_quality"] = evidence_quality
                if evidence_quality["accepted"]:
                    child_session.status = "completed"
                    child_session.metadata_ = metadata
                    set_session_run_state(child_session, RUN_STATUS_COMPLETED, "sub_agents_completed")
                else:
                    child_status = "failed"
                    run_status = RUN_STATUS_FAILED
                    run_completion_reason = "sub_agent_rejected"
                    rejection_summary = (
                        ", ".join(evidence_quality.get("rejection_reasons") or [])
                        or "unaccepted_sub_agent_evidence"
                    )
                    run_error = f"Sub-agent finished without accepted evidence: {rejection_summary}"
                    child_session.status = "error"
                    metadata["error"] = run_error
                    metadata["sub_agent_rejection_reasons"] = list(
                        evidence_quality.get("rejection_reasons") or []
                    )
                    child_session.metadata_ = metadata
                    set_session_run_state(child_session, RUN_STATUS_FAILED, run_completion_reason)
                db.add(child_session)
            await db.commit()
        await session_stream_manager.publish(
            session_id,
            "run_state",
            {
                "runStatus": run_status,
                "runCompletionReason": run_completion_reason,
                "error": run_error,
            },
        )
        await mark_sub_agent_group_child_terminal(
            session_factory=session_factory,
            group_id=group_id,
            child_session_id=session_id,
            child_status=child_status,
            error=run_error,
        )
    except asyncio.CancelledError as exc:
        cancel_reason = str(exc) or "sub_agent_cancelled"
        logger.info(
            "Sub-agent child run cancelled",
            extra={"group_id": group_id, "session_id": session_id, "reason": cancel_reason},
        )
        async with session_factory() as db:
            child_session = await db.get(Session, session_id)
            if child_session is not None:
                child_session.status = "stopped"
                child_session.ended_at = utc_now()
                metadata = dict(child_session.metadata_ or {})
                metadata["error"] = cancel_reason
                metadata["cancel_reason"] = cancel_reason
                metadata.pop("current_turn_user_message_id", None)
                child_session.metadata_ = metadata
                set_session_run_state(child_session, RUN_STATUS_FAILED, "sub_agent_cancelled")
                db.add(child_session)
            await db.commit()
        await session_stream_manager.publish(
            session_id,
            "run_state",
            {
                "runStatus": RUN_STATUS_FAILED,
                "runCompletionReason": "sub_agent_cancelled",
                "error": cancel_reason,
            },
        )
        await mark_sub_agent_group_child_terminal(
            session_factory=session_factory,
            group_id=group_id,
            child_session_id=session_id,
            child_status="failed",
            error=cancel_reason,
        )
        raise
    except Exception as exc:
        logger.exception("Sub-agent child run failed", extra={"group_id": group_id, "session_id": session_id})
        failure_text = error_text("sub_agent_child_failed", exc)
        async with session_factory() as db:
            child_session = await db.get(Session, session_id)
            if child_session is not None:
                child_session.status = "error"
                child_session.ended_at = utc_now()
                metadata = dict(child_session.metadata_ or {})
                metadata["error"] = failure_text
                metadata.pop("current_turn_user_message_id", None)
                child_session.metadata_ = metadata
                set_session_run_state(child_session, RUN_STATUS_FAILED, "sub_agent_failed")
                db.add(child_session)
            await db.commit()
        await session_stream_manager.publish(
            session_id,
            "run_state",
            {
                "runStatus": RUN_STATUS_FAILED,
                "runCompletionReason": "sub_agent_failed",
                "error": failure_text,
            },
        )
        await mark_sub_agent_group_child_terminal(
            session_factory=session_factory,
            group_id=group_id,
            child_session_id=session_id,
            child_status="failed",
            error=failure_text,
        )


async def _mark_child_session_cancelled(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    group_id: str,
    session_id: str,
    cancel_reason: str,
) -> None:
    async with session_factory() as db:
        child_session = await db.get(Session, session_id)
        if child_session is not None:
            child_session.status = "stopped"
            child_session.ended_at = utc_now()
            metadata = dict(child_session.metadata_ or {})
            metadata["error"] = cancel_reason
            metadata["cancel_reason"] = cancel_reason
            metadata.pop("current_turn_user_message_id", None)
            child_session.metadata_ = metadata
            set_session_run_state(child_session, RUN_STATUS_FAILED, "sub_agent_cancelled")
            db.add(child_session)
        await db.commit()
    await session_stream_manager.publish(
        session_id,
        "run_state",
        {
            "runStatus": RUN_STATUS_FAILED,
            "runCompletionReason": "sub_agent_cancelled",
            "error": cancel_reason,
        },
    )
    await mark_sub_agent_group_child_terminal(
        session_factory=session_factory,
        group_id=group_id,
        child_session_id=session_id,
        child_status="failed",
        error=cancel_reason,
    )


async def mark_sub_agent_group_child_terminal(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    group_id: str,
    child_session_id: str,
    child_status: str,
    error: str | None = None,
) -> None:
    should_resume_parent = False
    async with _group_lock(group_id):
        async with session_factory() as db:
            group = await db.get(SubAgentGroup, group_id)
            if group is None:
                return
            if str(group.status or "").strip().lower() not in {
                SUB_AGENT_GROUP_STATUS_RUNNING,
                SUB_AGENT_GROUP_STATUS_TIMED_OUT,
            }:
                return
            child_statuses = dict(group.child_statuses_json or {})
            existing = _terminal_child_status(child_statuses.get(child_session_id, ""))
            if existing in {"completed", "failed", "timed_out"}:
                return
            normalized_status = _terminal_child_status(child_status)
            child_statuses[child_session_id] = normalized_status
            group.child_statuses_json = child_statuses
            if error:
                group.last_error = error
            if await _reconcile_group_progress(db, group):
                if str(group.status or "").strip().lower() == SUB_AGENT_GROUP_STATUS_RUNNING:
                    group.status = SUB_AGENT_GROUP_STATUS_COMPLETED
                group.completed_at = utc_now()
                should_resume_parent = group.resumed_at is None
            db.add(group)
            await db.commit()
    if should_resume_parent:
        await _resume_parent_after_sub_agent_group(session_factory=session_factory, group_id=group_id)
    # release lock so _GROUP_LOCKS doesn't grow indefinitely
    _release_group_lock(group_id)


async def _watch_sub_agent_group_timeout(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    group_id: str,
) -> None:
    try:
        async with session_factory() as db:
            group = await db.get(SubAgentGroup, group_id)
            if group is None or group.timeout_at is None:
                return
            timeout_at = ensure_utc(group.timeout_at)
            if timeout_at is None:
                return
            delay_seconds = max(0.0, (timeout_at - utc_now_aware()).total_seconds())
        await asyncio.sleep(delay_seconds)
        should_resume_parent = False
        async with _group_lock(group_id):
            async with session_factory() as db:
                group = await db.get(SubAgentGroup, group_id)
                if group is None:
                    return
                if str(group.status or "").strip().lower() != SUB_AGENT_GROUP_STATUS_RUNNING:
                    return
                child_statuses = dict(group.child_statuses_json or {})
                child_session_ids = [
                    str(item).strip() for item in (group.child_session_ids_json or []) if str(item).strip()
                ]
                for child_session_id in child_session_ids:
                    if _terminal_child_status(child_statuses.get(child_session_id, "")) in {
                        "completed",
                        "failed",
                        "timed_out",
                    }:
                        continue
                    child_statuses[child_session_id] = "timed_out"
                    child_session = await db.get(Session, child_session_id)
                    if child_session is not None and child_session.status not in {"completed", "error"}:
                        child_session.status = "stopped"
                        child_session.ended_at = utc_now()
                        metadata = dict(child_session.metadata_ or {})
                        metadata["timeout_reason"] = "sub_agent_group_timeout"
                        metadata.pop("current_turn_user_message_id", None)
                        child_session.metadata_ = metadata
                        set_session_run_state(child_session, RUN_STATUS_FAILED, "sub_agent_timeout")
                        db.add(child_session)
                group.child_statuses_json = child_statuses
                await _reconcile_group_progress(db, group)
                group.status = SUB_AGENT_GROUP_STATUS_TIMED_OUT
                group.completed_at = utc_now()
                group.resume_prompt = await _group_prompt(db, group.parent_session_id, SUB_AGENT_TIMEOUT_PROMPT_KEY)
                db.add(group)
                await db.commit()
                should_resume_parent = group.resumed_at is None
        if should_resume_parent:
            await _resume_parent_after_sub_agent_group(session_factory=session_factory, group_id=group_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Sub-agent timeout watcher failed", extra={"group_id": group_id})
    finally:
        # release lock so _GROUP_LOCKS doesn't grow indefinitely
        _release_group_lock(group_id)
        task = _GROUP_TIMEOUT_TASKS.get(group_id)
        if task is asyncio.current_task():
            _GROUP_TIMEOUT_TASKS.pop(group_id, None)


async def _resume_parent_after_sub_agent_group(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    group_id: str,
) -> None:
    async with _group_lock(group_id):
        async with session_factory() as db:
            group = await db.get(SubAgentGroup, group_id)
            if group is None or group.resumed_at is not None:
                return
            parent_session = await db.get(Session, group.parent_session_id)
            parent_status = str(parent_session.status or "").strip().lower() if parent_session is not None else ""
            if parent_session is None or parent_status != "awaiting_subagents":
                return
            metadata = dict(parent_session.metadata_ or {})
            if str(metadata.get("current_sub_agent_group_id") or "").strip() != group.id:
                return
            if str(metadata.get("sub_agent_resume_started_group_id") or "").strip() == group.id:
                group.resumed_at = group.resumed_at or utc_now()
                group.status = SUB_AGENT_GROUP_STATUS_RESUMED
                db.add(group)
                await db.commit()
                return
            if group.created_at is not None:
                existing_parent_answer = (
                    await db.execute(
                        select(Message.id)
                        .where(
                            Message.session_id == parent_session.id,
                            Message.role == "assistant",
                            Message.created_at >= group.created_at,
                            Message.content.is_not(None),
                            Message.content != "",
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if existing_parent_answer:
                    group.resumed_at = utc_now()
                    group.status = SUB_AGENT_GROUP_STATUS_RESUMED
                    db.add(group)
                    await db.commit()
                    return
        if not await _wait_for_parent_resume_readiness(
            session_factory=session_factory,
            parent_session_id=group.parent_session_id,
        ):
            return
        async with session_factory() as db:
            group = await db.get(SubAgentGroup, group_id)
            if group is None or group.resumed_at is not None:
                return
            if not await _reconcile_group_progress(db, group):
                await db.commit()
                return
            parent_session = await db.get(Session, group.parent_session_id)
            if parent_session is None:
                return
            user = await db.get(User, parent_session.user_id)
            if user is None:
                return
            metadata = dict(parent_session.metadata_ or {})
            metadata["sub_agent_resume_started_group_id"] = group.id
            parent_session.metadata_ = metadata
            db.add(parent_session)
            resume_request = TurnRequest(
                user_id=user.id,
                prompt=await _build_group_resume_prompt(db, group),
                session_id=parent_session.id,
                project_id=parent_session.project_id or "",
                runtime_target_id=str(metadata.get("runtime_target_id") or ""),
                agent_id=str(metadata.get("agent_definition_id") or ""),
                agent_type=str(parent_session.agent_type or "diagnosis"),
                agent_type_explicit=False,
                thinking_level=str(metadata.get("thinking_level") or "light"),
            )
            group.resumed_at = utc_now()
            group.status = SUB_AGENT_GROUP_STATUS_RESUMED
            db.add(group)
            await db.commit()
            # Lazy: turn_start reaches the agent engine, whose tools import this module.
            from ..session.turn_start import start_turn

            started = await start_turn(resume_request, session_factory=session_factory)
            if isinstance(started, TurnRefusal):
                logger.warning(
                    "sub_agent_group.parent_resume_refused",
                    extra={"group_id": group_id, "session_id": resume_request.session_id, "state": started.state},
                )


async def _wait_for_parent_resume_readiness(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    parent_session_id: str,
    max_wait_seconds: float = 1.0,
) -> bool:
    deadline = asyncio.get_running_loop().time() + max_wait_seconds
    while asyncio.get_running_loop().time() < deadline:
        active_parent_task = CHAT_RUN_TASKS.get(parent_session_id)
        async with session_factory() as db:
            parent_session = await db.get(Session, parent_session_id)
            if parent_session is None:
                return False
            metadata = dict(parent_session.metadata_ or {})
            status = str(parent_session.status or "").strip().lower()
            if status == "running":
                pass
            elif status == "awaiting_subagents" and (
                not metadata.get("current_turn_user_message_id")
                or active_parent_task is None
                or active_parent_task.done()
            ):
                return True
            elif status in {"active", "completed", "error", "stopped"} and not metadata.get(
                "current_turn_user_message_id"
            ):
                return True
        await asyncio.sleep(0.05)
    return False


__all__ = [
    "SUB_AGENT_GROUP_STATUS_COMPLETED",
    "SUB_AGENT_GROUP_STATUS_RESUMED",
    "SUB_AGENT_GROUP_STATUS_RUNNING",
    "SUB_AGENT_GROUP_STATUS_TIMED_OUT",
    "SUB_AGENT_TIMEOUT_PROMPT_KEY",
    "SUB_AGENT_WAITING_PROMPT_KEY",
    "_GROUP_LOCKS",
    "_GROUP_CHILD_TASKS",
    "_GROUP_TIMEOUT_TASKS",
    "DEFAULT_SUB_AGENT_GROUP_TIMEOUT_SECONDS",
    "MAX_SUB_AGENT_GROUP_TIMEOUT_SECONDS",
    "MIN_SUB_AGENT_GROUP_TIMEOUT_SECONDS",
    "_build_group_resume_prompt",
    "_group_lock",
    "_resume_parent_after_sub_agent_group",
    "_run_child_session",
    "_terminal_child_status",
    "_wait_for_parent_resume_readiness",
    "_watch_sub_agent_group_timeout",
    "create_sub_agent_group",
    "launch_sub_agent_group",
    "logger",
    "mark_sub_agent_group_child_terminal",
    "normalize_sub_agent_group_timeout_seconds",
]
