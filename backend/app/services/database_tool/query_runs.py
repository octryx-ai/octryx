from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DatabaseQueryTool, DatabaseQueryToolRun
from ...time_utils import utc_now
from ...tools.context import ToolContext
from .runtime_policy import database_runtime_profile

MAX_AUDIT_ROWS = 5
MAX_AUDIT_FIELDS = 20
MAX_AUDIT_STRING_LENGTH = 300
MAX_ERROR_LENGTH = 500

_SECRET_KEY_MARKERS = ("api_key", "authorization", "dsn", "password", "secret", "token")
_SECRET_PATTERNS = [
    re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^@\s/]+@"),
    re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"(?i)(access[_-]?token\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"(?i)(token\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"(?i)(password\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"(?i)(secret\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"(?i)(connection[_-]?string\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"\b(ghp|github_pat|glpat|sk)-?[A-Za-z0-9_]{8,}\b"),
]


def sanitize_database_query_tool_error(value: Any, *, max_length: int = MAX_ERROR_LENGTH) -> str:
    sanitized = " ".join(str(value or "").replace("\n", " ").replace("\r", " ").split())
    for pattern in _SECRET_PATTERNS:
        if pattern.pattern.startswith("(?i)([a-z]"):
            sanitized = pattern.sub(r"\1[redacted]@", sanitized)
        else:
            sanitized = pattern.sub(_redacted_match, sanitized)
    if len(sanitized) > max_length:
        return f"{sanitized[: max_length - 3]}..."
    return sanitized


def classify_database_query_exception(exc: Exception) -> tuple[str, bool]:
    text = str(exc).lower()
    if any(marker in text for marker in ["permission", "forbidden", "unauthorized", "authorization", "privilege"]):
        return "provider_auth_failed", False
    configuration_markers = ["not found", "unknown database", "no such file", "invalid dsn", "does not exist"]
    if any(marker in text for marker in configuration_markers):
        return "configuration_failed", False
    if any(marker in text for marker in ["timeout", "temporarily", "connection refused", "connection reset"]):
        return "provider_retryable_failure", True
    return "query_execution_failed", True


async def create_database_query_tool_run(
    db: AsyncSession,
    *,
    tool: DatabaseQueryTool,
    context: ToolContext,
    params: dict[str, Any],
    applied_rls_rules: list[str],
) -> DatabaseQueryToolRun:
    run = DatabaseQueryToolRun(
        query_tool_id=tool.id,
        connector_id=tool.connector.id,
        project_id=tool.project_id or tool.connector.project_id,
        tool_name=tool.tool_name,
        connector_name=tool.connector.name,
        db_type=tool.connector.db_type,
        actor_user_id=context.user_id,
        session_id=context.session_id,
        status="running",
        max_rows=max(1, min(int(tool.max_rows or 100), 10000)),
        applied_rls_rules=list(applied_rls_rules or []),
        parameters_json=safe_database_query_audit_value(params or {}),
        evidence_json={
            "runtime_profile": database_runtime_profile(tool.connector.db_type),
            "rls_rule_count": len(applied_rls_rules or []),
            "context_project_count": len(context.project_ids or []),
            "context_role_count": len(context.roles or []),
        },
    )
    db.add(run)
    await db.flush()
    return run


async def complete_database_query_tool_run(
    db: AsyncSession,
    *,
    run: DatabaseQueryToolRun,
    rows: list[dict[str, Any]],
) -> None:
    now = utc_now()
    run.status = "succeeded"
    run.failure_category = None
    run.retryable = False
    run.error = None
    run.completed_at = now
    run.duration_ms = _duration_ms(run.started_at, now)
    run.row_count = len(rows)
    run.evidence_json = {
        **dict(run.evidence_json or {}),
        "row_count": len(rows),
        "row_preview": bounded_row_preview(rows),
        "row_preview_count": min(len(rows), MAX_AUDIT_ROWS),
        "row_preview_truncated": len(rows) > MAX_AUDIT_ROWS,
    }
    await db.flush()


async def fail_database_query_tool_run(
    db: AsyncSession,
    *,
    run: DatabaseQueryToolRun,
    message: Any,
    category: str,
    retryable: bool,
) -> None:
    now = utc_now()
    run.status = "failed"
    run.failure_category = category
    run.retryable = bool(retryable)
    run.error = sanitize_database_query_tool_error(message)
    run.completed_at = now
    run.duration_ms = _duration_ms(run.started_at, now)
    run.evidence_json = {
        **dict(run.evidence_json or {}),
        "failure_category": category,
        "retryable": bool(retryable),
    }
    await db.flush()


def query_run_result_metadata(run: DatabaseQueryToolRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "status": run.status,
        "failure_category": run.failure_category,
        "retryable": bool(run.retryable),
        "row_count": int(run.row_count or 0),
    }


def bounded_row_preview(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [safe_database_query_audit_value(row) for row in rows[:MAX_AUDIT_ROWS]]


def safe_database_query_audit_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 3:
        return "[truncated]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for index, (key, nested) in enumerate(value.items()):
            if index >= MAX_AUDIT_FIELDS:
                result["truncated_fields"] = True
                break
            key_text = str(key)
            lowered_key = key_text.lower()
            if any(marker in lowered_key for marker in _SECRET_KEY_MARKERS):
                result[key_text] = "[redacted]"
            else:
                result[key_text] = safe_database_query_audit_value(nested, depth=depth + 1)
        return result
    if isinstance(value, list):
        return [safe_database_query_audit_value(item, depth=depth + 1) for item in value[:MAX_AUDIT_ROWS]]
    if isinstance(value, str):
        return sanitize_database_query_tool_error(value, max_length=MAX_AUDIT_STRING_LENGTH)
    if isinstance(value, int | float | bool) or value is None:
        return value
    return sanitize_database_query_tool_error(str(value), max_length=MAX_AUDIT_STRING_LENGTH)


def _duration_ms(started_at: datetime | None, completed_at: datetime) -> int | None:
    if started_at is None:
        return None
    return max(0, int((completed_at - started_at).total_seconds() * 1000))


def _redacted_match(match: re.Match[str]) -> str:
    return f"{match.group(1)}[redacted]" if match.groups() else "[redacted]"
