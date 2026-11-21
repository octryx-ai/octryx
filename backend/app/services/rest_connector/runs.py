"""The audit row of every custom REST call (like ``DatabaseQueryToolRun``).

Who (user, session, Workspace), what (definition, operation, connection), as whom (``identity`` ``technical``: the
connection's account, not the person), within which scope (role, injected parameter names and values, result
filter, body fields), how many records were dropped as out of scope, what admitted a write (``approval_id`` or the
chat's ``write_plan_id``), and the outcome (status, HTTP status, duration). Arguments
are kept through the database tool's audit sanitizer (secret-looking keys and values redacted, bounded); a secret,
an auth header and a response body are never stored.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import RestApiCallRun
from ...time_utils import utc_now
from ..database_tool.query_runs import safe_database_query_audit_value, sanitize_database_query_tool_error
from ..secret_masking import masked

IDENTITY_TECHNICAL = "technical"
#: Failures decided by Octryx before or instead of the API answering: the run is ``refused``, not ``failed``.
REFUSAL_CATEGORIES = frozenset({"not_granted", "scope_violation", "capability_exceeded", "invalid_arguments",
                                "no_connection", "auth_config", "invalid_cursor", "scope_filter_unavailable",
                                "host_changed", "egress_refused"})


async def start_run(
    db: AsyncSession, *, definition: Any, operation: Any, tool_name: str, context: Any, workspace_id: str | None,
    arguments: dict[str, Any], admitted_by: dict[str, Any] | None = None,
) -> RestApiCallRun:
    """``admitted_by``: the approval or chat write plan the central gate admitted this call with (a write)."""
    admitted = admitted_by or {}
    run = RestApiCallRun(
        definition_id=definition.id,
        operation_id=operation.id,
        project_id=workspace_id,
        actor_user_id=getattr(context, "user_id", None),
        session_id=getattr(context, "session_id", None),
        tool_name=tool_name,
        identity=IDENTITY_TECHNICAL,
        status="running",
        scope_json={},
        arguments_json=safe_database_query_audit_value(masked(arguments or {})),
        approval_id=admitted.get("approval_id"),
        write_plan_id=admitted.get("write_plan_id"),
        started_at=utc_now(),
    )
    db.add(run)
    await db.flush()
    return run


def _finish(run: RestApiCallRun) -> None:
    run.completed_at = utc_now()
    if run.started_at is not None:
        run.duration_ms = max(0, int((run.completed_at - run.started_at).total_seconds() * 1000))


async def succeed_run(
    db: AsyncSession, run: RestApiCallRun, *, http_status: int, record_count: int, dropped_count: int
) -> None:
    run.status = "succeeded"
    run.http_status = http_status
    run.record_count = record_count
    run.dropped_count = dropped_count
    _finish(run)
    await db.flush()


async def fail_run(
    db: AsyncSession, run: RestApiCallRun, *, category: str, message: str, http_status: int | None = None,
    secrets: list[str] | None = None,
) -> None:
    text = str(message or "")
    for secret in secrets or []:
        if secret:
            text = text.replace(secret, "[redacted]")
    run.status = "refused" if category in REFUSAL_CATEGORIES else "failed"
    run.failure_category = category
    run.error = sanitize_database_query_tool_error(text)
    run.http_status = http_status
    _finish(run)
    await db.flush()


def run_payload(run: RestApiCallRun) -> dict[str, Any]:
    payload = {"id": run.id, "status": run.status, "failure_category": run.failure_category,
               "http_status": run.http_status, "dropped_out_of_scope": int(run.dropped_count or 0),
               "duration_ms": run.duration_ms}
    if run.approval_id or run.write_plan_id:
        payload["approval_id"] = run.approval_id
        payload["write_plan_id"] = run.write_plan_id
    return payload


__all__ = ["IDENTITY_TECHNICAL", "fail_run", "run_payload", "start_run", "succeed_run"]
