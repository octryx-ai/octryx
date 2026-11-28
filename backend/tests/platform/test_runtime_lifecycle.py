from __future__ import annotations

import pytest

import app.runtime_lifecycle as runtime_lifecycle
from app.runtime_lifecycle import get_task_scheduler, replace_platform_runtime_for_tests, set_runtime_session_factory
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
    assert payload["checks"]["task_queue_dispatcher"]["status"] == "disabled"
    assert "checks" in payload
    assert "database" in payload["checks"]
