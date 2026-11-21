"""A failed Jira intake run is recorded, not lost with the request.

A failure recorded inside the request would be discarded by the request's rollback, and the intake would keep showing
its last success. So the failure is written in its own transaction after the rollback (so nothing half-synced is kept),
with a fixed code and, where Jira explained itself, Jira's own message (a JQL error, never a secret, a header or a
body):

- ``scope_not_allowed``: the intake leaves the Workspace's ``jira_allowed_projects``;
- ``jql_invalid``: Jira refused the query (invalid, or unbounded on Cloud) with ``message``;
- ``intake_connection_unavailable``: the intake's named connection is gone from the Workspace;
- ``connection_disabled`` / ``connection_not_available`` / ``connection_use_disabled`` / ``connection_ambiguous``:
  the intake's connection refuses it (``named_connections/linked_use.py``);
- ``source_unauthorized``: Jira answered HTTP 401; the intake's connection is marked ``failing``
  (``named_connections/runtime_state.py``);
- ``jira_sync_failed``: anything else, with the exception type only.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkItemSyncConfig, WorkItemSyncRun
from ....time_utils import utc_now
from ...error_facts import error_type
from ...named_connections.runtime_state import AUTH_STATUS, record_runtime_failure
from ..intake.connections import connection_row_id

CODE_SCOPE_NOT_ALLOWED = "scope_not_allowed"
CODE_JQL_INVALID = "jql_invalid"
CODE_FAILED = "jira_sync_failed"
CODE_CONNECTION_UNAVAILABLE = "intake_connection_unavailable"
CODE_UNAUTHORIZED = "source_unauthorized"
CONNECTION_CODES = frozenset({"connection_disabled", "connection_not_available", "connection_use_disabled",
                              "connection_ambiguous"})
MAX_MESSAGE_CHARS = 500


def failure_facts(exc: BaseException) -> dict[str, Any]:
    """``{code, reason, message?}`` for a failed run; only fixed codes and Jira's JQL message."""
    detail = exc.detail if isinstance(exc, HTTPException) else None
    if isinstance(detail, dict) and detail.get("reason") == CODE_SCOPE_NOT_ALLOWED:
        projects = [str(key) for key in detail.get("projects") or []][:20]
        return {"code": CODE_SCOPE_NOT_ALLOWED, "reason": CODE_SCOPE_NOT_ALLOWED, "projects": projects}
    if isinstance(detail, dict) and detail.get("code") == CODE_CONNECTION_UNAVAILABLE:
        return {"code": CODE_CONNECTION_UNAVAILABLE, "reason": CODE_CONNECTION_UNAVAILABLE}
    if isinstance(detail, dict) and detail.get("code") in CONNECTION_CODES:
        return {"code": detail["code"], "reason": detail["code"]}
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == AUTH_STATUS:
        return {"code": CODE_UNAUTHORIZED, "reason": CODE_UNAUTHORIZED}
    if isinstance(detail, dict) and detail.get("code") == CODE_JQL_INVALID:
        message = str(detail.get("message") or "")[:MAX_MESSAGE_CHARS]
        return {"code": CODE_JQL_INVALID, "reason": CODE_JQL_INVALID, "message": message}
    return {"code": CODE_FAILED, "reason": CODE_FAILED, "error_type": error_type(exc)}


def run_values(run: WorkItemSyncRun) -> dict[str, Any]:
    """The run's identity, read before a rollback expires it."""
    return {
        "sync_config_id": run.sync_config_id,
        "triggered_by": run.triggered_by,
        "mode": run.mode,
        "limit": run.limit,
        "query_preview": run.query_preview,
    }


async def record_failed_run(
    db: AsyncSession, *, config_id: str, values: dict[str, Any], exc: BaseException, trigger: str | None = None
) -> None:
    """Roll the failed attempt back, then record the failed run and the config's status durably."""
    await db.rollback()
    facts = failure_facts(exc)
    now = utc_now()
    db.add(
        WorkItemSyncRun(
            **values,
            status="failed",
            summary_json={**facts, "trigger": trigger} if trigger else facts,
            sample_items_json=[],
            error=facts["code"],
            started_at=now,
            completed_at=now,
        )
    )
    config = await db.get(WorkItemSyncConfig, config_id)
    if config is not None:
        config.last_sync_at = now
        config.last_sync_status = "failed"
        config.last_sync_summary_json = {**facts, "query_preview": values.get("query_preview") or ""}
        if facts["code"] == CODE_UNAUTHORIZED:
            await record_runtime_failure(db, await connection_row_id(db, config, "jira"), "tickets")
    await db.commit()


__all__ = [
    "CODE_FAILED",
    "CODE_UNAUTHORIZED",
    "CODE_JQL_INVALID",
    "CODE_SCOPE_NOT_ALLOWED",
    "failure_facts",
    "record_failed_run",
    "run_values",
]
