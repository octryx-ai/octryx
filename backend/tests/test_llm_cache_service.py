from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.models import LLMCacheEntry
from app.services.llm_cache import (
    build_llm_cache_prompt_hash,
    lookup_cached_llm_response,
    select_llm_cache_ttl_seconds,
    store_llm_cache_response,
)
from app.time_utils import utc_now


@pytest.mark.asyncio
async def test_llm_cache_service_stores_and_reuses_plain_response(db):
    messages = [
        {"role": "system", "content": "You are precise."},
        {"role": "user", "content": "Reply with CACHE."},
    ]
    runtimes = [
        {
            "provider_id": "provider-a",
            "provider_name": "copilot",
            "model": "claude-haiku-4.5",
            "target_id": "runtime-a",
            "priority": 1,
        }
    ]

    stored = await store_llm_cache_response(
        db,
        provider_id="provider-a",
        model_id="claude-haiku-4.5",
        messages=messages,
        tools=None,
        max_tokens=1024,
        reasoning_effort="medium",
        response={
            "content": "CACHE",
            "tool_calls": None,
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 8, "completion_tokens": 1, "total_tokens": 9},
        },
        ttl_seconds=300,
        cache_scope="default",
    )

    assert stored is not None

    cached = await lookup_cached_llm_response(
        db,
        runtimes=runtimes,
        messages=messages,
        tools=None,
        max_tokens=1024,
        reasoning_effort="medium",
    )

    assert cached is not None
    response, runtime, attempts = cached
    assert response["content"] == "CACHE"
    assert response["cached"] is True
    assert response["usage"]["prompt_tokens"] == 0
    assert response["usage"]["completion_tokens"] == 0
    assert response["usage"]["total_tokens"] == 0
    assert runtime["provider_id"] == "provider-a"
    assert attempts[-1]["status"] == "cache_hit"

    refreshed = await db.get(LLMCacheEntry, stored.id)
    assert refreshed is not None
    assert refreshed.hit_count == 1


@pytest.mark.asyncio
async def test_llm_cache_service_ignores_expired_entries(db):
    entry = LLMCacheEntry(
        id=str(uuid.uuid4()),
        prompt_hash=build_llm_cache_prompt_hash(
            messages=[{"role": "user", "content": "hello"}],
            tools=None,
            max_tokens=256,
            reasoning_effort=None,
        ),
        provider_id="provider-expired",
        model_id="model-expired",
        response_json={"content": "stale", "tool_calls": None},
        hit_count=0,
        cache_scope="default",
        expires_at=utc_now() - timedelta(seconds=5),
    )
    db.add(entry)
    await db.commit()

    cached = await lookup_cached_llm_response(
        db,
        runtimes=[{"provider_id": "provider-expired", "provider_name": "copilot", "model": "model-expired"}],
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        max_tokens=256,
        reasoning_effort=None,
    )

    assert cached is None


@pytest.mark.asyncio
async def test_llm_cache_service_skips_tool_call_responses(db):
    stored = await store_llm_cache_response(
        db,
        provider_id="provider-tools",
        model_id="model-tools",
        messages=[{"role": "user", "content": "do work"}],
        tools=[{"name": "bash"}],
        max_tokens=512,
        reasoning_effort="low",
        response={
            "content": "I should call tools",
            "tool_calls": [{"name": "bash", "arguments": {"command": "pwd"}}],
        },
        ttl_seconds=120,
        cache_scope="tools",
    )

    assert stored is None
    entries = (await db.execute(select(LLMCacheEntry))).scalars().all()
    assert entries == []


def test_select_llm_cache_ttl_seconds_uses_tool_scope_when_tools_present():
    ttl, scope = select_llm_cache_ttl_seconds(
        tools=[{"name": "bash"}],
        default_ttl_seconds=300,
        tools_ttl_seconds=120,
    )
    assert ttl == 120
    assert scope == "tools"


@pytest.mark.asyncio
async def test_store_llm_cache_response_skips_sqlite_lock_without_failing_run(db, monkeypatch):
    rollback_calls = {"count": 0}

    async def _locked_commit() -> None:
        raise OperationalError("INSERT", {}, Exception("database is locked"))

    async def _counting_rollback() -> None:
        rollback_calls["count"] += 1

    monkeypatch.setattr(db, "commit", _locked_commit)
    monkeypatch.setattr(db, "rollback", _counting_rollback)

    stored = await store_llm_cache_response(
        db,
        provider_id="provider-lock",
        model_id="model-lock",
        messages=[{"role": "user", "content": "Reply with CACHE."}],
        tools=None,
        max_tokens=128,
        reasoning_effort="low",
        response={"content": "CACHE", "tool_calls": None},
        ttl_seconds=120,
        cache_scope="default",
    )

    assert stored is None
    assert rollback_calls["count"] == 1


@pytest.mark.asyncio
async def test_lookup_cached_llm_response_returns_cached_payload_when_hit_count_commit_locks(db, monkeypatch):
    entry = LLMCacheEntry(
        id=str(uuid.uuid4()),
        prompt_hash=build_llm_cache_prompt_hash(
            messages=[{"role": "user", "content": "hello"}],
            tools=None,
            max_tokens=256,
            reasoning_effort=None,
        ),
        provider_id="provider-hit-lock",
        model_id="model-hit-lock",
        response_json={"content": "cached", "tool_calls": None},
        hit_count=0,
        cache_scope="default",
        expires_at=utc_now() + timedelta(seconds=120),
    )
    db.add(entry)
    await db.commit()

    rollback_calls = {"count": 0}

    async def _locked_commit() -> None:
        raise OperationalError("UPDATE", {}, Exception("database is locked"))

    async def _counting_rollback() -> None:
        rollback_calls["count"] += 1

    monkeypatch.setattr(db, "commit", _locked_commit)
    monkeypatch.setattr(db, "rollback", _counting_rollback)

    cached = await lookup_cached_llm_response(
        db,
        runtimes=[{"provider_id": "provider-hit-lock", "provider_name": "copilot", "model": "model-hit-lock"}],
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        max_tokens=256,
        reasoning_effort=None,
    )

    assert cached is not None
    response, runtime, attempts = cached
    assert response["content"] == "cached"
    assert response["cached"] is True
    assert runtime["provider_id"] == "provider-hit-lock"
    assert attempts[-1]["status"] == "cache_hit"
    assert rollback_calls["count"] == 1
