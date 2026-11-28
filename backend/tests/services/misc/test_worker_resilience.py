from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.exc import OperationalError

import app.services.analytics.service as analytics_service_module
import app.services.observability as observability_service_module


def _sqlite_lock_error() -> OperationalError:
    return OperationalError("INSERT", {}, Exception("database is locked"))


class _FakeSession:
    def __init__(self, factory_state: dict[str, int]) -> None:
        self._state = factory_state

    def add(self, _obj) -> None:
        return None

    async def commit(self) -> None:
        self._state["commit_attempts"] += 1
        if self._state["commit_attempts"] < 3:
            raise _sqlite_lock_error()


class _FakeSessionFactory:
    def __init__(self) -> None:
        self.state = {"enter_count": 0, "commit_attempts": 0}

    def __call__(self):
        factory = self

        class _Context:
            async def __aenter__(self):
                factory.state["enter_count"] += 1
                return _FakeSession(factory.state)

            async def __aexit__(self, exc_type, exc, tb):
                return False

        return _Context()


def test_record_request_counter_normalizes_endpoint_labels():
    counter = observability_service_module._HTTP_REQUEST_COUNTER
    observability_service_module.reset_db_concurrency_events()
    counter.clear()
    try:
        observability_service_module.record_request_counter(
            "/api/v1/sessions/123e4567-e89b-12d3-a456-426614174000",
            "get",
            200,
        )
        observability_service_module.record_request_counter("/api/v1/sessions/{id}", "GET", 200)

        assert counter[("/api/v1/sessions/{id}", "GET", "200")] == 2
        assert len(counter) == 1
    finally:
        counter.clear()


@pytest.mark.asyncio
async def test_analytics_worker_skips_iteration_after_sqlite_lock(monkeypatch):
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)
        raise asyncio.CancelledError()

    async def fake_aggregate_due_analytics(_db) -> int:
        raise _sqlite_lock_error()

    async def fake_process_pending_report_exports(_db) -> int:
        pytest.fail("report exports should not run after aggregate lock")

    class _SessionFactory:
        def __call__(self):
            class _Context:
                async def __aenter__(self):
                    return object()

                async def __aexit__(self, exc_type, exc, tb):
                    return False

            return _Context()

    monkeypatch.setattr(analytics_service_module, "aggregate_due_analytics", fake_aggregate_due_analytics)
    monkeypatch.setattr(analytics_service_module, "process_pending_report_exports", fake_process_pending_report_exports)
    monkeypatch.setattr(analytics_service_module.asyncio, "sleep", fake_sleep)

    worker = analytics_service_module.AnalyticsWorker(
        _SessionFactory(),
        interval_seconds=45,
        startup_delay_seconds=0,
    )

    with pytest.raises(asyncio.CancelledError):
        await worker._run_loop()

    assert delays == [45]
