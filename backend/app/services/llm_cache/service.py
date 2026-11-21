"""LLM response cache helpers."""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import LLMCacheEntry
from ...time_utils import utc_now


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _is_sqlite_lock_error(exc: Exception) -> bool:
    return "database is locked" in str(exc).lower()


def build_llm_cache_prompt_hash(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    reasoning_effort: str | None,
) -> str:
    payload = {
        "messages": messages,
        "tools": tools or [],
        "max_tokens": int(max_tokens or 0),
        "reasoning_effort": str(reasoning_effort or "").strip().lower(),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def select_llm_cache_ttl_seconds(
    *,
    tools: list[dict[str, Any]] | None,
    default_ttl_seconds: int,
    tools_ttl_seconds: int,
) -> tuple[int, str]:
    if tools:
        return max(0, int(tools_ttl_seconds or 0)), "tools"
    return max(0, int(default_ttl_seconds or 0)), "default"


def _cache_attempt(runtime: dict[str, Any], provider_name: str, model_name: str, status: str) -> dict[str, Any]:
    return {
        "provider": provider_name,
        "model": model_name,
        "target_id": runtime.get("target_id"),
        "priority": runtime.get("priority"),
        "status": status,
    }


def _cached_response(row: LLMCacheEntry, model_name: str) -> dict[str, Any]:
    cached_response = copy.deepcopy(row.response_json or {})
    cached_response["usage"] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached": True,
    }
    cached_response["model"] = cached_response.get("model") or model_name
    cached_response["cached"] = True
    return cached_response


async def lookup_cached_llm_response(
    db: AsyncSession,
    *,
    runtimes: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    reasoning_effort: str | None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]] | None:
    prompt_hash = build_llm_cache_prompt_hash(
        messages=messages,
        tools=tools,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
    )
    now = utc_now()
    attempts: list[dict[str, Any]] = []
    for runtime in runtimes:
        provider_id = str(runtime.get("provider_id") or runtime.get("provider_name") or "").strip()
        provider_name = str(runtime.get("provider_name") or provider_id).strip()
        model_name = str(runtime.get("model") or "").strip()
        row = (
            await db.execute(
                select(LLMCacheEntry).where(
                    LLMCacheEntry.prompt_hash == prompt_hash,
                    LLMCacheEntry.provider_id == provider_id,
                    LLMCacheEntry.model_id == model_name,
                    LLMCacheEntry.expires_at > now,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            attempts.append(_cache_attempt(runtime, provider_name, model_name, "cache_miss"))
            continue
        row.hit_count = int(row.hit_count or 0) + 1
        try:
            await db.commit()
        except OperationalError as exc:
            await db.rollback()
            if not _is_sqlite_lock_error(exc):
                raise
        cached_response = _cached_response(row, model_name)
        attempts.append(
            {
                **_cache_attempt(runtime, provider_name, model_name, "cache_hit"),
                "cache_entry_id": row.id,
                "hit_count": row.hit_count,
            }
        )
        return cached_response, runtime, attempts
    return None


async def _upsert_cache_row(
    db: AsyncSession,
    *,
    prompt_hash: str,
    provider_id: str,
    model_id: str,
    payload: dict[str, Any],
    cache_scope: str,
    expires_at: Any,
) -> LLMCacheEntry:
    row = (
        await db.execute(
            select(LLMCacheEntry).where(
                LLMCacheEntry.prompt_hash == prompt_hash,
                LLMCacheEntry.provider_id == provider_id,
                LLMCacheEntry.model_id == model_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = LLMCacheEntry(
            id=str(uuid.uuid4()),
            prompt_hash=prompt_hash,
            provider_id=provider_id,
            model_id=model_id,
            response_json=payload,
            hit_count=0,
            cache_scope=cache_scope,
            expires_at=expires_at,
        )
        db.add(row)
    else:
        row.response_json = payload
        row.expires_at = expires_at
        row.cache_scope = cache_scope
    return row


async def store_llm_cache_response(
    db: AsyncSession,
    *,
    provider_id: str,
    model_id: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    reasoning_effort: str | None,
    response: dict[str, Any],
    ttl_seconds: int,
    cache_scope: str,
) -> LLMCacheEntry | None:
    normalized_ttl = max(0, int(ttl_seconds or 0))
    if normalized_ttl <= 0:
        return None
    normalized_provider_id = str(provider_id or "").strip()
    normalized_model_id = str(model_id or "").strip()
    if not normalized_provider_id or not normalized_model_id:
        return None
    if response.get("tool_calls"):
        return None
    if not str(response.get("content") or "").strip():
        return None

    prompt_hash = build_llm_cache_prompt_hash(
        messages=messages,
        tools=tools,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
    )
    expires_at = utc_now() + timedelta(seconds=normalized_ttl)
    row = await _upsert_cache_row(
        db,
        prompt_hash=prompt_hash,
        provider_id=normalized_provider_id,
        model_id=normalized_model_id,
        payload=copy.deepcopy(response),
        cache_scope=cache_scope,
        expires_at=expires_at,
    )
    try:
        await db.commit()
    except OperationalError as exc:
        await db.rollback()
        if _is_sqlite_lock_error(exc):
            return None
        raise
    except SQLAlchemyError:
        await db.rollback()
        raise
    return row
