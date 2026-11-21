from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import FailedTaskRun
from ...circuit_breaker import describe_failed_task_run, list_circuit_breakers


async def admin_list_circuit_breakers(db: AsyncSession) -> dict:
    failed_rows = (
        (await db.execute(select(FailedTaskRun).order_by(FailedTaskRun.status.asc(), FailedTaskRun.updated_at.desc())))
        .scalars()
        .all()
    )
    return {
        "circuit_breakers": await list_circuit_breakers(db),
        "failed_task_runs": [
            _serialize_failed_task_run(row)
            for row in failed_rows
        ],
    }


def _serialize_failed_task_run(row: FailedTaskRun) -> dict:
    decision = describe_failed_task_run(row).as_dict()
    return {
        "id": row.id,
        "task_id": row.task_id,
        "task_run_id": row.task_run_id,
        "retry_count": int(row.retry_count or 0),
        "last_error": row.last_error,
        "next_retry_at": row.next_retry_at.isoformat() if row.next_retry_at else None,
        "status": row.status,
        "retryable": decision["retryable"],
        "terminal": decision["terminal"],
        "reason": decision["reason"],
        "queue_status": decision["queue_status"],
        "task_run_status": decision["task_run_status"],
        "retry_policy": decision["retry_policy"],
        "decision": decision,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
