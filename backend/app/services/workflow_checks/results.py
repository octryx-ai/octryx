"""Stored check results (A6): one ``workflow_check_results`` row per checked turn, and the list view.

States: ``passed`` (no blocking check failed) and ``not_verified`` (platform chat accepted the
answer after the one reminder).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.runtime.workflow_check import WorkflowCheckResult
from .library import CheckResult, failed_blocking

RUNTIME_CHAT = "chat"
STATE_PASSED = "passed"
STATE_NOT_VERIFIED = "not_verified"
MAX_LISTED = 200
# The context-snapshot key of the chat turn's check record (the trace shows it next to answer_evidence).
WORKFLOW_CHECKS_KEY = "workflow_checks"


_RECORD_STATES = frozenset({STATE_PASSED, STATE_NOT_VERIFIED, "reminded"})
_OUTCOMES = frozenset({"passed", "failed", "not_applicable", "skipped"})


def read_workflow_checks(context_snapshot: object) -> dict[str, Any] | None:
    """The validated check record of a trace's context snapshot, or ``None`` (closed values, bounded)."""
    record = context_snapshot.get(WORKFLOW_CHECKS_KEY) if isinstance(context_snapshot, dict) else None
    if not isinstance(record, dict) or record.get("state") not in _RECORD_STATES:
        return None
    results = [
        {"type": str(item.get("type") or "")[:40], "outcome": item.get("outcome"),
         "blocking": item.get("blocking") is True,
         "description": str(item.get("description") or "")[:300], "detail": str(item.get("detail") or "")[:300]}
        for item in record.get("results") or [] if isinstance(item, dict) and item.get("outcome") in _OUTCOMES
    ][:20]
    return {"workflow_key": str(record.get("workflow_key") or "")[:180], "state": record["state"],
            "reminded": record.get("reminded") is True, "results": results}


def check_state(results: Sequence[CheckResult], *, failed_state: str = STATE_NOT_VERIFIED) -> str:
    return failed_state if failed_blocking(results) else STATE_PASSED


def check_record(workflow_key: str, state: str, results: Sequence[CheckResult], *, reminded: bool) -> dict[str, Any]:
    return {
        "workflow_key": workflow_key,
        "state": state,
        "reminded": reminded,
        "results": [result.as_dict() for result in results],
    }


async def store_check_result(
    db: AsyncSession,
    *,
    session_id: str | None,
    trace_id: str | None,
    workflow_key: str,
    workflow_version: int | None,
    runtime: str,
    state: str,
    results: Sequence[CheckResult],
) -> WorkflowCheckResult:
    row = WorkflowCheckResult(
        session_id=session_id,
        trace_id=trace_id,
        workflow_key=workflow_key,
        workflow_version=workflow_version,
        runtime=runtime,
        state=state,
        results_json=[result.as_dict() for result in results],
    )
    db.add(row)
    await db.flush()
    return row


def serialize_check_result(row: WorkflowCheckResult) -> dict[str, Any]:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "trace_id": row.trace_id,
        "workflow_key": row.workflow_key,
        "workflow_version": row.workflow_version,
        "runtime": row.runtime,
        "state": row.state,
        "results": row.results_json if isinstance(row.results_json, list) else [],
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def list_check_results(
    db: AsyncSession,
    *,
    workflow_key: str | None = None,
    session_id: str | None = None,
    runtime: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    stmt = select(WorkflowCheckResult).order_by(WorkflowCheckResult.created_at.desc())
    if workflow_key:
        stmt = stmt.where(WorkflowCheckResult.workflow_key == workflow_key)
    if session_id:
        stmt = stmt.where(WorkflowCheckResult.session_id == session_id)
    if runtime:
        stmt = stmt.where(WorkflowCheckResult.runtime == runtime)
    rows = (await db.execute(stmt.limit(max(1, min(limit, MAX_LISTED))))).scalars().all()
    return [serialize_check_result(row) for row in rows]


__all__ = [
    "MAX_LISTED",
    "RUNTIME_CHAT",
    "STATE_NOT_VERIFIED",
    "STATE_PASSED",
    "WORKFLOW_CHECKS_KEY",
    "check_record",
    "check_state",
    "read_workflow_checks",
    "list_check_results",
    "serialize_check_result",
    "store_check_result",
]
