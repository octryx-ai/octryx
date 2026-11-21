from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..models import BackgroundWorkerRunState
from ..time_utils import utc_now

logger = logging.getLogger(__name__)

BACKGROUND_WORKER_ERROR_MAX_CHARS = 500

_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/\-=]+"),
    re.compile(r"(?i)((?:api[_-]?key|access[_-]?token|token|password|secret|authorization)\s*[:=]\s*)[^\s,&]+"),
    re.compile(r"(?i)(://[^:/\s]+:)[^@/\s]+(@)"),
    re.compile(r"(?i)\b(gh[pousr]_[A-Za-z0-9_]{10,})\b"),
    re.compile(r"(?i)\b(glpat-[A-Za-z0-9_\-]{10,})\b"),
    re.compile(r"(?i)\b(sk-[A-Za-z0-9_\-]{10,})\b"),
)


def sanitize_background_worker_error(value: object) -> str:
    message = str(value or "Background worker failed").replace("\r", " ").replace("\n", " ").strip()
    for pattern in _SECRET_VALUE_PATTERNS:
        if pattern.pattern.startswith("(?i)(bearer"):
            message = pattern.sub(r"\1[REDACTED]", message)
        elif "://" in pattern.pattern:
            message = pattern.sub(r"\1[REDACTED]\2", message)
        else:
            message = pattern.sub(lambda match: _redact_secret_match(match), message)
    if len(message) > BACKGROUND_WORKER_ERROR_MAX_CHARS:
        message = message[: BACKGROUND_WORKER_ERROR_MAX_CHARS - 3].rstrip() + "..."
    return message or "Background worker failed"


def _redact_secret_match(match: re.Match[str]) -> str:
    if match.lastindex and match.lastindex >= 1:
        prefix = match.group(1)
        if prefix.lower().startswith(("gh", "glpat", "sk-")):
            return "[REDACTED]"
        return f"{prefix}[REDACTED]"
    return "[REDACTED]"


async def record_background_worker_success(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    worker_name: str,
    owner: str,
    started_at: datetime,
    result: object = None,
) -> None:
    completed_at = utc_now()
    details = summarize_background_worker_result(result)
    await _record_background_worker_run_state(
        session_factory,
        worker_name=worker_name,
        owner=owner,
        status="success",
        started_at=started_at,
        completed_at=completed_at,
        processed_count=int(details.get("processed_count") or 0),
        details=details,
        error=None,
        retryable=False,
    )


async def record_background_worker_failure(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    worker_name: str,
    owner: str,
    started_at: datetime,
    error: object,
    retryable: bool = True,
) -> None:
    completed_at = utc_now()
    await _record_background_worker_run_state(
        session_factory,
        worker_name=worker_name,
        owner=owner,
        status="failed",
        started_at=started_at,
        completed_at=completed_at,
        processed_count=0,
        details={"result_type": "error"},
        error=sanitize_background_worker_error(error),
        retryable=retryable,
    )


def summarize_background_worker_result(result: object) -> dict[str, Any]:
    if isinstance(result, list):
        return {"result_type": "list", "processed_count": len(result)}
    if isinstance(result, Mapping):
        counts: dict[str, int] = {}
        for key, value in result.items():
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                counts[str(key)] = int(value)
            elif isinstance(value, list):
                counts[f"{key}_count"] = len(value)
            elif isinstance(value, Mapping):
                counts[f"{key}_count"] = len(value)
        processed_count = _processed_count_from_counts(counts)
        return {
            "result_type": "dict",
            "keys": sorted(str(key) for key in result.keys()),
            "counts": counts,
            "processed_count": processed_count,
        }
    if isinstance(result, bool):
        return {"result_type": "bool", "processed_count": 1 if result else 0}
    return {"result_type": type(result).__name__, "processed_count": 0}


def _processed_count_from_counts(counts: Mapping[str, int]) -> int:
    for key in (
        "processed_count",
        "processed",
        "workers_checked",
        "connectors_checked",
        "alerts_created",
        "deleted_count",
        "sent_count",
    ):
        if key in counts:
            return int(counts[key])
    return max((int(value) for value in counts.values()), default=0)


async def _record_background_worker_run_state(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    worker_name: str,
    owner: str,
    status: str,
    started_at: datetime,
    completed_at: datetime,
    processed_count: int,
    details: dict[str, Any],
    error: str | None,
    retryable: bool,
) -> None:
    try:
        async with session_factory() as db:
            row = (
                await db.execute(
                    select(BackgroundWorkerRunState).where(BackgroundWorkerRunState.worker_name == worker_name)
                )
            ).scalar_one_or_none()
            if row is None:
                row = BackgroundWorkerRunState(
                    worker_name=worker_name,
                    owner=owner,
                    status=status,
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_ms=0,
                    processed_count=0,
                    details_json={},
                    run_count=0,
                    failure_count=0,
                    updated_at=completed_at,
                )
                db.add(row)
            row.owner = owner
            row.status = status
            row.started_at = started_at
            row.completed_at = completed_at
            row.duration_ms = max(0, int((completed_at - started_at).total_seconds() * 1000))
            row.processed_count = max(0, int(processed_count or 0))
            row.details_json = details
            row.error = error
            row.retryable = bool(retryable)
            row.run_count = int(row.run_count or 0) + 1
            row.failure_count = int(row.failure_count or 0) + (1 if status == "failed" else 0)
            row.updated_at = completed_at
            await db.commit()
    except Exception:
        logger.exception("Failed to persist background worker run state", extra={"worker_name": worker_name})
