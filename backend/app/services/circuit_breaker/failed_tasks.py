"""Failed task runs: retry scheduling with backoff, terminal refusals, and resolution."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import FailedTaskRun
from ...time_utils import utc_now
from .policy import (
    FAILED_TASK_ADMISSION_REFUSED_STATUS,
    FAILED_TASK_CONTENT_BLOCKED_STATUS,
    FAILED_TASK_REPLY_CONTRACT_VIOLATION_STATUS,
    FAILED_TASK_RESOLVED_STATUS,
    FAILED_TASK_RETRY_DELAYS_SECONDS,
    FAILED_TASK_RETRYABLE_STATUS,
    FAILED_TASK_RUNTIME_STOPPED_STATUS,
    FAILED_TASK_TERMINAL_STATUS,
    TaskFailureDecision,
    describe_failed_task_run,
    sanitize_task_failure_message,
)


async def register_failed_task_run(
    db: AsyncSession,
    *,
    task_id: str,
    task_run_id: str,
    error: str,
) -> tuple[FailedTaskRun, int | None]:
    safe_error = sanitize_task_failure_message(error)
    row = FailedTaskRun(
        task_id=task_id,
        task_run_id=task_run_id,
        retry_count=1,
        last_error=safe_error,
        status=FAILED_TASK_RETRYABLE_STATUS,
        next_retry_at=utc_now() + timedelta(seconds=FAILED_TASK_RETRY_DELAYS_SECONDS[0]),
    )
    db.add(row)
    await db.flush()
    delay = FAILED_TASK_RETRY_DELAYS_SECONDS[0]
    return row, delay


async def escalate_failed_task_run(
    db: AsyncSession,
    *,
    task_id: str,
    task_run_id: str,
    error: str,
    trigger_id: str | None,
) -> tuple[FailedTaskRun, int | None]:
    if trigger_id:
        row = await db.get(FailedTaskRun, trigger_id)
        if row is None:
            row, delay = await register_failed_task_run(db, task_id=task_id, task_run_id=task_run_id, error=error)
            return row, delay
        row.task_run_id = task_run_id
        row.retry_count = int(row.retry_count or 0) + 1
        row.last_error = sanitize_task_failure_message(error)
        if row.retry_count > len(FAILED_TASK_RETRY_DELAYS_SECONDS):
            row.status = FAILED_TASK_TERMINAL_STATUS
            row.next_retry_at = None
            return row, None
        delay = FAILED_TASK_RETRY_DELAYS_SECONDS[row.retry_count - 1]
        row.status = FAILED_TASK_RETRYABLE_STATUS
        row.next_retry_at = utc_now() + timedelta(seconds=delay)
        return row, delay

    row, delay = await register_failed_task_run(db, task_id=task_id, task_run_id=task_run_id, error=error)
    return row, delay


async def record_admission_refused_task_run(
    db: AsyncSession,
    *,
    task_id: str,
    task_run_id: str,
    error: str,
    trigger_id: str | None,
) -> FailedTaskRun:
    """Record a terminal admission refusal; a refused retry attempt ends its chain and keeps its history."""
    return await _record_terminal_task_run(
        db,
        status=FAILED_TASK_ADMISSION_REFUSED_STATUS,
        task_id=task_id,
        task_run_id=task_run_id,
        error=error,
        trigger_id=trigger_id,
    )


async def _record_terminal_task_run(
    db: AsyncSession,
    *,
    status: str,
    task_id: str,
    task_run_id: str,
    error: str,
    trigger_id: str | None,
) -> FailedTaskRun:
    row = await db.get(FailedTaskRun, trigger_id) if trigger_id else None
    if row is None:
        row = FailedTaskRun(task_id=task_id, task_run_id=task_run_id, retry_count=1)
        db.add(row)
    else:
        row.task_run_id = task_run_id
        row.retry_count = int(row.retry_count or 0) + 1
    row.last_error = sanitize_task_failure_message(error)
    row.status = status
    row.next_retry_at = None
    await db.flush()
    return row


async def escalate_failed_task_run_decision(
    db: AsyncSession,
    *,
    task_id: str,
    task_run_id: str,
    error: str,
    trigger_id: str | None,
    admission_refused: bool = False,
    reply_contract_violation: bool = False,
    runtime_stopped: bool = False,
    content_blocked: bool = False,
) -> tuple[FailedTaskRun, TaskFailureDecision]:
    """The failure decision."""
    terminal_status = None
    if content_blocked is True:
        terminal_status = FAILED_TASK_CONTENT_BLOCKED_STATUS
    elif admission_refused is True:
        terminal_status = FAILED_TASK_ADMISSION_REFUSED_STATUS
    elif reply_contract_violation is True:
        terminal_status = FAILED_TASK_REPLY_CONTRACT_VIOLATION_STATUS
    elif runtime_stopped is True:
        terminal_status = FAILED_TASK_RUNTIME_STOPPED_STATUS
    if terminal_status is not None:
        row = await _record_terminal_task_run(
            db, status=terminal_status, task_id=task_id, task_run_id=task_run_id, error=error, trigger_id=trigger_id
        )
        return row, describe_failed_task_run(row)
    row, retry_delay = await escalate_failed_task_run(
        db,
        task_id=task_id,
        task_run_id=task_run_id,
        error=error,
        trigger_id=trigger_id,
    )
    return row, describe_failed_task_run(row, retry_delay_seconds=retry_delay)


async def resolve_failed_task_run(db: AsyncSession, *, trigger_id: str | None) -> None:
    if not trigger_id:
        return
    row = await db.get(FailedTaskRun, trigger_id)
    if row is None:
        return
    row.status = FAILED_TASK_RESOLVED_STATUS
    row.next_retry_at = None
    await db.commit()
