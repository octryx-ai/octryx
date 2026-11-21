"""The Bedrock model catalog read is bounded and single-flight.

- The ``bedrock`` control-plane client is built with connect 3 s, read 5 s, one attempt.
- One read per region at a time: concurrent callers (also from another event loop) await the same read.
- A failed read keeps the existing prefix rule and is retried only after 5 minutes.

The catalog is a stub (slow or raising); no AWS call is made.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest

from app.agent.providers import bedrock_model_ids
from app.agent.providers.bedrock_model_ids import (
    FAILED_READ_TTL_SECONDS,
    catalog_inference_types,
    list_foundation_model_summaries,
    resolve_bedrock_model_id,
)

QWEN = "qwen.qwen3-32b-v1:0"
CATALOG = [{"modelId": QWEN, "inferenceTypesSupported": ["ON_DEMAND"]}]


class _SlowCatalog:
    def __init__(self, *, delay: float = 0.3, error: Exception | None = None) -> None:
        self.delay = delay
        self.error = error
        self.reads = 0
        self.concurrent = 0
        self.max_concurrent = 0
        self._lock = threading.Lock()

    def __call__(self) -> list[dict[str, Any]]:
        with self._lock:
            self.reads += 1
            self.concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            time.sleep(self.delay)
            if self.error is not None:
                raise self.error
            return list(CATALOG)
        finally:
            with self._lock:
                self.concurrent -= 1


@pytest.fixture(autouse=True)
def _fresh_catalog():
    bedrock_model_ids.clear_catalog_cache()
    yield
    bedrock_model_ids.clear_catalog_cache()


async def test_concurrent_callers_share_one_read_per_region():
    slow = _SlowCatalog()
    results = await asyncio.gather(*(catalog_inference_types("eu-central-1", QWEN, slow) for _ in range(8)))
    assert results == [frozenset({"ON_DEMAND"})] * 8
    assert slow.reads == 1

    # Another region is its own read.
    await catalog_inference_types("us-east-1", QWEN, slow)
    assert slow.reads == 2


def test_callers_on_other_event_loops_share_the_read_too():
    slow = _SlowCatalog(delay=0.4)
    results: list[Any] = []

    def caller() -> None:
        results.append(asyncio.run(catalog_inference_types("eu-west-1", QWEN, slow)))

    threads = [threading.Thread(target=caller) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [frozenset({"ON_DEMAND"})] * 4
    assert slow.reads == 1 and slow.max_concurrent == 1


async def test_a_cancelled_caller_does_not_cancel_the_read_others_await():
    slow = _SlowCatalog()
    first = asyncio.create_task(catalog_inference_types("eu-central-1", QWEN, slow))
    second = asyncio.create_task(catalog_inference_types("eu-central-1", QWEN, slow))
    await asyncio.sleep(0.05)
    first.cancel()
    assert await second == frozenset({"ON_DEMAND"})
    assert slow.reads == 1


async def test_a_caller_cancelled_while_the_read_is_still_queued_does_not_cancel_it(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    reader = ThreadPoolExecutor(max_workers=1)
    gate = threading.Event()
    reader.submit(gate.wait)  # the pool is busy, so the catalog read waits in the queue
    monkeypatch.setattr(bedrock_model_ids, "_READER", reader)
    slow = _SlowCatalog(delay=0.0)
    try:
        first = asyncio.create_task(catalog_inference_types("eu-central-1", QWEN, slow))
        second = asyncio.create_task(catalog_inference_types("eu-central-1", QWEN, slow))
        await asyncio.sleep(0.05)
        first.cancel()
        await asyncio.sleep(0.05)
        gate.set()
        assert await asyncio.wait_for(second, timeout=5) == frozenset({"ON_DEMAND"})
        assert slow.reads == 1
    finally:
        gate.set()
        reader.shutdown(wait=True)


async def test_a_failed_read_keeps_the_prefix_rule_and_is_retried_after_five_minutes(monkeypatch):
    failing = _SlowCatalog(delay=0.05, error=RuntimeError("ReadTimeoutError"))
    clock = [1000.0]
    monkeypatch.setattr(bedrock_model_ids.time, "monotonic", lambda: clock[0])

    types = await asyncio.gather(*(catalog_inference_types("eu-central-1", QWEN, failing) for _ in range(5)))
    assert types == [None] * 5 and failing.reads == 1
    assert resolve_bedrock_model_id(QWEN, region="eu-central-1", inference_types=None) == f"eu.{QWEN}"

    clock[0] += FAILED_READ_TTL_SECONDS - 1
    assert await catalog_inference_types("eu-central-1", QWEN, failing) is None
    assert failing.reads == 1

    clock[0] += 2
    healthy = _SlowCatalog(delay=0.0)
    assert await catalog_inference_types("eu-central-1", QWEN, healthy) == frozenset({"ON_DEMAND"})
    assert healthy.reads == 1
    assert FAILED_READ_TTL_SECONDS == 300.0


def test_the_control_plane_client_is_bounded(monkeypatch):
    import boto3

    built: list[dict[str, Any]] = []

    class _Bedrock:
        def list_foundation_models(self) -> dict[str, Any]:
            return {"modelSummaries": list(CATALOG)}

    def client(service: str, **kwargs: Any) -> _Bedrock:
        built.append({"service": service, **kwargs})
        return _Bedrock()

    monkeypatch.setattr(boto3, "client", client)
    assert list_foundation_model_summaries({"region_name": "eu-central-1"}) == CATALOG
    [call] = built
    assert call["service"] == "bedrock" and call["region_name"] == "eu-central-1"
    config = call["config"]
    assert (config.connect_timeout, config.read_timeout, config.retries) == (3, 5, {"max_attempts": 1})
