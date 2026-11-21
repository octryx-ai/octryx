from __future__ import annotations

import pytest

import app.runtime_lifecycle as runtime_lifecycle
import app.runtime_setup as runtime_setup
from app.runtime_lifecycle import get_task_scheduler, replace_platform_runtime_for_tests, set_runtime_session_factory
from app.runtime_setup import PlatformRuntime
from app.runtime_toggles import DISABLE_BACKGROUND_WORKERS_ENV


class _FakeScheduler:
    def __init__(self) -> None:
        self.started = False
        self.shutdown_called = False
        self.session_factory = None

    async def start(self) -> None:
        self.started = True

    def shutdown(self) -> None:
        self.shutdown_called = True

    def set_session_factory(self, session_factory) -> None:
        self.session_factory = session_factory


class _FakeAsyncWorker:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start(self, *args) -> None:
        self.started = True
        self.start_args = args

    async def stop(self) -> None:
        self.stopped = True


class _FakeChannelRouter(_FakeAsyncWorker):
    async def start(self, session_factory) -> None:
        self.started = True
        self.session_factory = session_factory


def test_runtime_container_updates_runtime_and_scheduler_session_factory() -> None:
    scheduler = _FakeScheduler()
    runtime = type("FakeRuntime", (), {"async_session_factory": "old", "task_scheduler": scheduler})()
    # Restore the singleton the app already holds, not None: a rebuilt singleton would
    # diverge from ``app.main.platform_runtime``, and later tests in this process would
    # sync the session factory into an object the health and metrics routes never read.
    previous_runtime = runtime_lifecycle._platform_runtime
    replace_platform_runtime_for_tests(runtime)
    try:
        result = set_runtime_session_factory("new")
        assert result is runtime
        assert runtime.async_session_factory == "new"
        assert scheduler.session_factory == "new"
        assert get_task_scheduler() is scheduler
    finally:
        replace_platform_runtime_for_tests(previous_runtime)


@pytest.mark.asyncio
async def test_platform_runtime_starts_and_stops_scheduler_background_workers(monkeypatch):
    scheduler = _FakeScheduler()
    channel_router = _FakeChannelRouter()
    prefetch_worker = _FakeAsyncWorker()
    workers = [_FakeAsyncWorker() for _ in range(11)]
    projection_worker = _FakeAsyncWorker()
    session_factory = object()

    monkeypatch.setattr(runtime_setup, "channel_message_router", channel_router)
    monkeypatch.setattr(runtime_setup, "prefetch_worker", prefetch_worker)
    runtime = PlatformRuntime(
        async_session_factory=session_factory,
        task_scheduler=scheduler,
        retention_worker=workers[0],
        notification_delivery_worker=workers[1],
        outbound_webhook_worker=workers[2],
        connector_health_worker=workers[3],
        analytics_worker=workers[4],
        knowledge_projection_worker=projection_worker,
        worker_monitor_worker=workers[5],
        worker_agenda_worker=workers[6],
        worker_report_worker=workers[7],
        worker_pool_worker=workers[8],
        sla_monitor_worker=workers[9],
        secret_expiry_worker=workers[10],
        session_workspace_cleanup_worker=_FakeAsyncWorker(),
        runtime_ownership_worker=_FakeAsyncWorker(),
    )

    await runtime._start_background_workers(knowledge_projection_enabled=True)
    assert scheduler.started is True
    # Perf step 2: the channel router runs in every process (channels startup), not with the workers.
    assert channel_router.started is False
    assert prefetch_worker.started is True
    assert projection_worker.started is True
    assert all(worker.started for worker in workers)
    assert runtime.session_workspace_cleanup_worker.started is True

    await runtime._stop_background_workers()
    assert scheduler.shutdown_called is True
    assert channel_router.stopped is False
    assert prefetch_worker.stopped is True
    assert projection_worker.stopped is True
    assert all(worker.stopped for worker in workers)
    assert runtime.session_workspace_cleanup_worker.stopped is True

    projection_worker.started = False
    projection_worker.stopped = False
    await runtime._start_background_workers(knowledge_projection_enabled=False)
    await runtime._stop_background_workers()
    assert projection_worker.started is False
    assert projection_worker.stopped is False


@pytest.mark.asyncio
async def test_health_endpoint_remains_available(client, auth_headers, monkeypatch) -> None:
    # The test client never runs the lifespan, so no background worker is started. The
    # dispatcher is a critical component (a stopped one is an overall error);
    # declare the workers disabled so the endpoint reports that explicit state instead.
    monkeypatch.setenv(DISABLE_BACKGROUND_WORKERS_ENV, "1")
    response = await client.get("/api/v1/health", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"ok", "degraded"}
    assert payload["checks"]["task_queue_dispatcher"]["error"] == "disabled"
    # Disabled is its own state, never "ok" (observability O4).
    assert payload["checks"]["task_queue_dispatcher"]["status"] == "disabled"
    assert "checks" in payload
    assert "database" in payload["checks"]
