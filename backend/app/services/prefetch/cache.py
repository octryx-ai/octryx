"""Cache and freshness helpers for predictive tool prefetching."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import PrefetchCacheEntry
from ...time_utils import utc_now

logger = logging.getLogger(__name__)
root_logger = logging.getLogger()

_DEFAULT_PREFETCH_TTL_SECONDS = 300
_FAST_CHANGING_PREFETCH_TTL_SECONDS = 30
_TARGETED_JIRA_PREFETCH_TTL_SECONDS = 120
_CACHEABLE_PREFETCH_TOOLS = {
    "get_k8s_events",
    "list_failed_pods",
    "search_jira_tickets",
}


def _log_info(message: str, *args: object, **kwargs: Any) -> None:
    logger.info(message, *args, **kwargs)
    if logger.disabled or not logger.propagate:
        record = logger.makeRecord(
            logger.name,
            logging.INFO,
            fn="",
            lno=0,
            msg=message,
            args=args,
            exc_info=None,
            extra=kwargs.get("extra"),
        )
        root_logger.handle(record)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def build_prefetch_params_hash(tool_name: str, params: dict[str, Any]) -> str:
    import hashlib

    payload = {"tool_name": str(tool_name or "").strip(), "params": params or {}}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value
    return value.replace(tzinfo=utc_now().tzinfo)


def get_prefetch_cacheability_reason(tool_name: str, params: dict[str, Any] | None = None) -> str | None:
    if select_prefetch_cache_ttl_seconds(tool_name, params) > 0:
        return None
    return "tool_not_cacheable"


def select_prefetch_cache_ttl_seconds(tool_name: str, params: dict[str, Any] | None = None) -> int:
    normalized = str(tool_name or "").strip()
    effective_params = params if isinstance(params, dict) else {}
    if normalized not in _CACHEABLE_PREFETCH_TOOLS:
        return 0

    # Prefetched data can sit idle before a user consumes it, so operational
    # read tools use stricter freshness than the direct session-tool cache.
    if normalized in {"list_failed_pods", "get_k8s_events"}:
        return _FAST_CHANGING_PREFETCH_TTL_SECONDS
    if normalized == "search_jira_tickets":
        query = str(effective_params.get("query") or "").strip()
        if query:
            return _TARGETED_JIRA_PREFETCH_TTL_SECONDS
        return _DEFAULT_PREFETCH_TTL_SECONDS
    return _DEFAULT_PREFETCH_TTL_SECONDS


def prefetch_cache_is_fresh(row: PrefetchCacheEntry | None, *, now: datetime | None = None) -> bool:
    if row is None:
        return False
    ttl_seconds = select_prefetch_cache_ttl_seconds(str(row.tool_name or "").strip(), row.params_json)
    if ttl_seconds <= 0:
        return False
    completed_at = _as_utc(row.completed_at or row.created_at)
    if completed_at is None:
        return False
    effective_now = _as_utc(now) or utc_now()
    return completed_at.timestamp() + ttl_seconds > effective_now.timestamp()


async def lookup_prefetch_cache(
    db: AsyncSession,
    *,
    session_id: str,
    tool_name: str,
    params: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    params_hash = build_prefetch_params_hash(tool_name, params)
    row = (
        await db.execute(
            select(PrefetchCacheEntry).where(
                PrefetchCacheEntry.session_id == session_id,
                PrefetchCacheEntry.tool_name == tool_name,
                PrefetchCacheEntry.params_hash == params_hash,
                PrefetchCacheEntry.status == "completed",
            )
        )
    ).scalar_one_or_none()
    if row is None or not isinstance(row.result_json, dict):
        return None
    if not prefetch_cache_is_fresh(row):
        return None
    completed_at = _as_utc(row.completed_at or row.created_at)
    return dict(row.result_json), {
        "prefetch_cache_entry_id": row.id,
        "prefetched_at": completed_at.isoformat() if completed_at else "",
        "ttl_seconds": select_prefetch_cache_ttl_seconds(tool_name, row.params_json),
    }


async def store_prefetch_cache_result(
    db: AsyncSession,
    *,
    session_id: str,
    tool_name: str,
    params: dict[str, Any],
    result: dict[str, Any],
) -> PrefetchCacheEntry | None:
    cacheability_reason = get_prefetch_cacheability_reason(tool_name, params)
    if cacheability_reason is not None:
        _log_info(
            "Prefetch cache write suppressed by governance",
            extra={"session_id": session_id, "tool_name": tool_name, "reason": cacheability_reason},
        )
        return None
    if not isinstance(result, dict):
        _log_info(
            "Prefetch cache write suppressed by governance",
            extra={"session_id": session_id, "tool_name": tool_name, "reason": "non_mapping_result"},
        )
        return None
    if result.get("error") or result.get("approval_required"):
        reason = "approval_required" if result.get("approval_required") else "tool_error"
        _log_info(
            "Prefetch cache write suppressed by governance",
            extra={"session_id": session_id, "tool_name": tool_name, "reason": reason},
        )
        return None
    params_hash = build_prefetch_params_hash(tool_name, params)
    existing = (
        await db.execute(
            select(PrefetchCacheEntry).where(
                PrefetchCacheEntry.session_id == session_id,
                PrefetchCacheEntry.tool_name == tool_name,
                PrefetchCacheEntry.params_hash == params_hash,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = PrefetchCacheEntry(
            session_id=session_id,
            tool_name=tool_name,
            params_hash=params_hash,
        )
        db.add(existing)
    existing.params_json = dict(params)
    existing.result_json = dict(result)
    existing.status = "completed"
    existing.completed_at = utc_now()
    await db.commit()
    await db.refresh(existing)
    return existing
