from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from ...config import get_settings

try:
    from redis.asyncio import Redis
    from redis.asyncio import from_url as redis_from_url
except Exception:  # pragma: no cover - optional dependency/runtime
    Redis = Any  # type: ignore[assignment]
    redis_from_url = None

_CLIENTS: dict[str, Redis] = {}
_QUEUE_KEY = "octryx:task-queue:global"
_PAYLOAD_HASH_KEY = "octryx:task-queue:payloads"


def _serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _queue_score(priority: int, queued_at: datetime | None) -> float:
    # Lower score wins in zpopmin. High priority first, FIFO within same priority.
    bounded_priority = max(1, min(int(priority or 5), 10))
    priority_bucket = 10 - bounded_priority
    ts_ms = int((queued_at.timestamp() if queued_at else 0) * 1000)
    return float(priority_bucket * 10_000_000_000_000 + ts_ms)


async def get_redis_client(redis_url: str | None = None) -> Redis | None:
    url = str(redis_url or get_settings().redis_url or "").strip()
    if not url or redis_from_url is None:
        return None
    client = _CLIENTS.get(url)
    if client is None:
        client = redis_from_url(url, decode_responses=True)
        _CLIENTS[url] = client
    return client


async def is_redis_queue_available(redis_url: str | None = None) -> bool:
    client = await get_redis_client(redis_url)
    if client is None:
        return False
    try:
        return bool(await client.ping())
    except Exception:
        return False


async def task_queue_depth(redis_url: str | None = None, *, timeout: float = 1.0) -> int | None:
    """Entries waiting in the Redis task queue (``ZCARD``), or ``None`` without Redis or without an answer in time."""
    import asyncio

    client = await get_redis_client(redis_url)
    if client is None:
        return None
    try:
        return int(await asyncio.wait_for(client.zcard(_QUEUE_KEY), timeout))
    except Exception:  # noqa: BLE001 - no depth rather than a failed scrape
        return None


async def enqueue_task_queue_entry(
    *,
    entry_id: str,
    project_id: str | None,
    task_run_id: str,
    task_id: str,
    priority: int,
    queued_at: datetime | None,
    required_domain: str | None,
    required_worker_id: str | None,
    redis_url: str | None = None,
) -> bool:
    client = await get_redis_client(redis_url)
    if client is None:
        return False
    payload = {
        "entry_id": entry_id,
        "project_id": project_id,
        "task_run_id": task_run_id,
        "task_id": task_id,
        "priority": int(priority or 5),
        "queued_at": _serialize_datetime(queued_at),
        "required_domain": required_domain,
        "required_worker_id": required_worker_id,
        "redis_url": redis_url,
    }
    score = _queue_score(int(priority or 5), queued_at)
    await client.hset(_PAYLOAD_HASH_KEY, entry_id, json.dumps(payload))
    await client.zadd(_QUEUE_KEY, {entry_id: score})
    return True


async def pop_next_task_queue_entry(*, redis_url: str | None = None) -> dict[str, Any] | None:
    client = await get_redis_client(redis_url)
    if client is None:
        return None
    popped = await client.zpopmin(_QUEUE_KEY, count=1)
    if not popped:
        return None
    entry_id = str(popped[0][0])
    payload = await client.hget(_PAYLOAD_HASH_KEY, entry_id)
    if not payload:
        return {"entry_id": entry_id}
    data = json.loads(payload)
    data["entry_id"] = entry_id
    return data


async def requeue_task_queue_entries(entries: Iterable[dict[str, Any]], *, redis_url: str | None = None) -> None:
    client = await get_redis_client(redis_url)
    if client is None:
        return
    score_map: dict[str, float] = {}
    for entry in entries:
        entry_id = str(entry.get("entry_id") or "").strip()
        if not entry_id:
            continue
        queued_at_raw = entry.get("queued_at")
        queued_at = None
        if isinstance(queued_at_raw, str) and queued_at_raw:
            try:
                queued_at = datetime.fromisoformat(queued_at_raw)
            except ValueError:
                queued_at = None
        score_map[entry_id] = _queue_score(int(entry.get("priority") or 5), queued_at)
        await client.hset(_PAYLOAD_HASH_KEY, entry_id, json.dumps(entry))
    if score_map:
        await client.zadd(_QUEUE_KEY, score_map)


async def remove_task_queue_entry(entry_id: str, *, redis_url: str | None = None) -> None:
    client = await get_redis_client(redis_url)
    if client is None:
        return
    await client.zrem(_QUEUE_KEY, entry_id)
    await client.hdel(_PAYLOAD_HASH_KEY, entry_id)


async def sync_pending_task_queue_entries(entries: Iterable[dict[str, Any]], *, redis_url: str | None = None) -> int:
    synced = 0
    for entry in entries:
        ok = await enqueue_task_queue_entry(
            entry_id=str(entry["entry_id"]),
            project_id=entry.get("project_id"),
            task_run_id=str(entry["task_run_id"]),
            task_id=str(entry["task_id"]),
            priority=int(entry.get("priority") or 5),
            queued_at=entry.get("queued_at"),
            required_domain=entry.get("required_domain"),
            required_worker_id=entry.get("required_worker_id"),
            redis_url=redis_url,
        )
        if ok:
            synced += 1
    return synced
