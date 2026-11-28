"""What would the open draft block in live traffic?"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import PolicyDraftImpact, PolicySetVersion
from ...time_utils import utc_now
from ..redaction_policy import redact_secret_text
from .points import PointQuery

MAX_PRINCIPALS = 50
MAX_SAMPLES = 5
MAX_BUCKETS = 5000
MAX_HOURS = 720
PRUNE_SECONDS = 3600.0
SAMPLE_RESOURCE_CHARS = 240

_LOCK = threading.Lock()
_BUCKETS: dict[tuple[str, int, str, str, str, datetime], dict[str, Any]] = {}
# ``last_prune`` starts at minus infinity, not 0: ``time.monotonic()`` counts from about the boot, so a host up
# for less than an hour (a fresh CI runner or node) would otherwise wait for its first prune.
_STATE: dict[str, Any] = {"dropped": 0, "last_prune": float("-inf")}


def _hour(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def _principal_hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()[:16]


def record_draft_denial(*, draft_digest: str, draft_version: int, query: PointQuery,
                        policy_ids: Iterable[str]) -> None:
    now = utc_now()
    principal = _principal_hash(query.principal.label())
    sample = {"time": now.isoformat(), "point": query.point, "action": query.action,
              "workspace_id": query.workspace_id[:64], "principal": principal,
              "resource": redact_secret_text(query.log_resource or query.resource, max_chars=SAMPLE_RESOURCE_CHARS)}
    with _LOCK:
        for policy_id in policy_ids:
            key = (draft_digest, int(draft_version), str(policy_id)[:120], query.point, query.action, _hour(now))
            bucket = _BUCKETS.get(key)
            if bucket is None:
                if len(_BUCKETS) >= MAX_BUCKETS:
                    _STATE["dropped"] += 1
                    continue
                bucket = _BUCKETS[key] = {"count": 0, "principals": set(), "samples": []}
            bucket["count"] += 1
            if len(bucket["principals"]) < MAX_PRINCIPALS:
                bucket["principals"].add(principal)
            if len(bucket["samples"]) < MAX_SAMPLES:
                bucket["samples"].append(sample)


def pending_buckets() -> int:
    return len(_BUCKETS)


def reset_draft_impact() -> None:
    with _LOCK:
        _BUCKETS.clear()
        _STATE["dropped"], _STATE["last_prune"] = 0, float("-inf")


def draft_prune_due() -> bool:
    now = time.monotonic()
    with _LOCK:
        if now - _STATE["last_prune"] < PRUNE_SECONDS:
            return False
        _STATE["last_prune"] = now
    return True


def _take() -> dict[tuple, dict[str, Any]]:
    with _LOCK:
        taken = dict(_BUCKETS)
        _BUCKETS.clear()
    return taken


def _merged(values: list, more: Iterable, limit: int) -> list:
    merged = list(values)
    for item in more:
        if len(merged) >= limit:
            break
        if item not in merged:
            merged.append(item)
    return merged


async def _bucket_row(db: AsyncSession, digest: str, policy_id: str, point: str, action: str,
                      hour: datetime) -> PolicyDraftImpact | None:
    return (await db.execute(select(PolicyDraftImpact).where(
        PolicyDraftImpact.draft_digest == digest, PolicyDraftImpact.policy_id == policy_id,
        PolicyDraftImpact.point == point, PolicyDraftImpact.action == action, PolicyDraftImpact.hour == hour,
    ))).scalar_one_or_none()


def _add(row: PolicyDraftImpact, bucket: dict[str, Any], now: datetime) -> None:
    row.count = int(row.count or 0) + bucket["count"]
    row.principals = _merged(list(row.principals or []), sorted(bucket["principals"]), MAX_PRINCIPALS)
    row.samples = _merged(list(row.samples or []), bucket["samples"], MAX_SAMPLES)
    row.updated_at = now


async def _write(db: AsyncSession, taken: dict[tuple, dict[str, Any]]) -> None:
    now = utc_now()
    for (digest, version, policy_id, point, action, hour), bucket in taken.items():
        row = await _bucket_row(db, digest, policy_id, point, action, hour)
        if row is not None:
            _add(row, bucket, now)
            await db.flush()
            continue
        row = PolicyDraftImpact(draft_digest=digest, draft_version=version, policy_id=policy_id, point=point,
                                action=action, hour=hour, count=0, principals=[], samples=[])
        _add(row, bucket, now)
        try:
            async with db.begin_nested():
                db.add(row)
        except IntegrityError:  # inserted by a concurrent flush since the read: add to that row
            existing = await _bucket_row(db, digest, policy_id, point, action, hour)
            if existing is None:
                raise
            _add(existing, bucket, now)
            await db.flush()


async def prune_draft_impact(db: AsyncSession, *, days: int) -> None:
    await db.execute(delete(PolicyDraftImpact).where(PolicyDraftImpact.hour < utc_now() - timedelta(days=days)))


async def flush_draft_impact(db: AsyncSession | None = None, *, prune_days: int | None = None) -> int:
    taken = _take()
    if not taken and prune_days is None:
        return 0
    if db is not None:
        await _write(db, taken)
        if prune_days is not None:
            await prune_draft_impact(db, days=prune_days)
        return len(taken)
    from ...db import core as db_core

    async with db_core.async_session_factory() as session:
        await _write(session, taken)
        if prune_days is not None:
            await prune_draft_impact(session, days=prune_days)
        await session.commit()
    return len(taken)


def _pending_for(digest: str, since: datetime) -> list[dict[str, Any]]:
    with _LOCK:
        return [{"policy_id": key[2], "point": key[3], "action": key[4], "count": bucket["count"],
                 "principals": sorted(bucket["principals"]), "samples": list(bucket["samples"])}
                for key, bucket in _BUCKETS.items() if key[0] == digest and key[5] >= _hour(since)]


async def draft_impact_view(db: AsyncSession, row: PolicySetVersion, *, hours: int) -> dict[str, Any]:
    window = max(1, min(int(hours), MAX_HOURS))
    since = utc_now() - timedelta(hours=window)
    stored = (await db.execute(select(PolicyDraftImpact).where(
        PolicyDraftImpact.draft_digest == row.digest, PolicyDraftImpact.hour >= _hour(since)))).scalars()
    entries = [{"policy_id": item.policy_id, "point": item.point, "action": item.action, "count": item.count,
                "principals": list(item.principals or []), "samples": list(item.samples or [])} for item in stored]
    entries += _pending_for(str(row.digest), since)
    policies: dict[str, dict[str, Any]] = {}
    for entry in entries:
        policy = policies.setdefault(entry["policy_id"], {"count": 0, "points": {}, "actions": {}, "principals": set(),
                                                          "samples": []})
        policy["count"] += entry["count"]
        policy["points"][entry["point"]] = policy["points"].get(entry["point"], 0) + entry["count"]
        policy["actions"][entry["action"]] = policy["actions"].get(entry["action"], 0) + entry["count"]
        policy["principals"].update(entry["principals"])
        policy["samples"] = _merged(policy["samples"], entry["samples"], MAX_SAMPLES)
    for policy in policies.values():
        policy["principals"] = len(policy["principals"])
        policy["samples"].sort(key=lambda item: item.get("time", ""), reverse=True)
    return {"version": row.version, "digest": row.digest, "hours": window, "since": since.isoformat(),
            "total": sum(policy["count"] for policy in policies.values()), "policies": dict(sorted(policies.items()))}


__all__ = [
    "draft_impact_view",
    "draft_prune_due",
    "flush_draft_impact",
    "pending_buckets",
    "prune_draft_impact",
    "record_draft_denial",
    "reset_draft_impact",
]
