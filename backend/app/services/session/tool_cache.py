from __future__ import annotations

import copy
import hashlib
import json
import uuid
from datetime import UTC, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import SessionToolCacheEntry
from ...time_utils import utc_now, utc_now_aware

LOG_TOOLS = {"query_loki", "get_pod_logs"}
K8S_TOOLS = {"get_k8s_events", "list_failed_pods", "get_k8s_deployments"}
JIRA_TOOLS = {"search_jira_tickets"}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _as_utc(value: Any):
    if value is None:
        return None
    if getattr(value, "tzinfo", None) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def build_session_tool_cache_hash(tool_name: str, params: dict[str, Any]) -> str:
    payload = {
        "tool_name": str(tool_name or "").strip(),
        "params": params or {},
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _run_kubectl_ttl_seconds(params: dict[str, Any]) -> int:
    command = params.get("command")
    args = params.get("args")
    tokens: list[str] = []
    if isinstance(command, str):
        tokens.extend(command.split())
    elif isinstance(command, list):
        tokens.extend(str(part) for part in command)
    if isinstance(args, list):
        tokens.extend(str(part) for part in args)
    lowered = [token.strip().lower() for token in tokens if str(token).strip()]
    if not lowered:
        return 0
    if "logs" in lowered:
        return 0
    if any(token in {"get", "describe", "top"} for token in lowered):
        return 60
    return 0


def select_session_tool_cache_ttl_seconds(tool_name: str, params: dict[str, Any]) -> int:
    normalized = str(tool_name or "").strip()
    if normalized in LOG_TOOLS:
        return 0
    if normalized == "run_kubectl":
        return _run_kubectl_ttl_seconds(params)
    if normalized in K8S_TOOLS:
        return 60
    if normalized in JIRA_TOOLS or (
        normalized.startswith("list_jira_") and normalized not in {"list_jira_transitions"}
    ):
        return 300
    return 0


async def lookup_session_tool_cache(
    db: AsyncSession,
    *,
    session_id: str,
    tool_name: str,
    params: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    ttl_seconds = select_session_tool_cache_ttl_seconds(tool_name, params)
    if ttl_seconds <= 0:
        return None
    params_hash = build_session_tool_cache_hash(tool_name, params)
    row = (
        await db.execute(
            select(SessionToolCacheEntry).where(
                SessionToolCacheEntry.session_id == session_id,
                SessionToolCacheEntry.tool_name == str(tool_name or "").strip(),
                SessionToolCacheEntry.params_hash == params_hash,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    now = utc_now_aware()
    cached_at = _as_utc(row.cached_at)
    if cached_at is None or cached_at + timedelta(seconds=int(row.ttl_seconds or 0)) <= now:
        return None
    row.hit_count = int(row.hit_count or 0) + 1
    await db.commit()
    metadata = {
        "cache_entry_id": row.id,
        "ttl_seconds": int(row.ttl_seconds or 0),
        "hit_count": int(row.hit_count or 0),
        "cached_at": cached_at.isoformat() if cached_at else None,
    }
    return copy.deepcopy(row.result_json or {}), metadata


async def store_session_tool_cache(
    db: AsyncSession,
    *,
    session_id: str,
    tool_name: str,
    params: dict[str, Any],
    result: dict[str, Any],
) -> SessionToolCacheEntry | None:
    ttl_seconds = select_session_tool_cache_ttl_seconds(tool_name, params)
    if ttl_seconds <= 0:
        return None
    if not isinstance(result, dict):
        return None
    if result.get("error") or result.get("approval_required"):
        return None
    params_hash = build_session_tool_cache_hash(tool_name, params)
    row = (
        await db.execute(
            select(SessionToolCacheEntry).where(
                SessionToolCacheEntry.session_id == session_id,
                SessionToolCacheEntry.tool_name == str(tool_name or "").strip(),
                SessionToolCacheEntry.params_hash == params_hash,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = SessionToolCacheEntry(
            id=str(uuid.uuid4()),
            session_id=session_id,
            tool_name=str(tool_name or "").strip(),
            params_hash=params_hash,
        )
        db.add(row)
    row.result_json = copy.deepcopy(result)
    row.cached_at = utc_now()
    row.ttl_seconds = int(ttl_seconds)
    await db.commit()
    return row
