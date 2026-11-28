"""The worker entrypoint with its health probe, the API worker count passed to uvicorn and the cross-process startup lock."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

import app.worker_main as worker_main
from app.runtime_toggles import (
    API_WORKERS_ENV,
    DISABLE_BACKGROUND_WORKERS_ENV,
    SKIP_CHAT_BUILD_ENV,
    SKIP_IMAGE_PLUGINS_ENV,
    api_worker_count,
)


class _HealthRuntime:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.runtime_ownership_worker = SimpleNamespace(is_running=lambda: self.started and not self.stopped)
        self.task_scheduler = SimpleNamespace(_queue_dispatch_task=None)

    async def startup(self) -> None:
        self.started = True
        self.task_scheduler._queue_dispatch_task = asyncio.get_running_loop().create_future()

    async def shutdown(self) -> None:
        self.stopped = True


async def _get(port: int, path: str) -> tuple[int, dict]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET {path} HTTP/1.1\r\nHost: probe\r\n\r\n".encode())
    await writer.drain()
    raw = await reader.read()
    writer.close()
    head, _, body = raw.partition(b"\r\n\r\n")
    return int(head.split()[1]), json.loads(body or b"{}")


@pytest.mark.asyncio
async def test_worker_entrypoint_starts_the_workers_and_serves_health(monkeypatch) -> None:
    runtime = _HealthRuntime()
    monkeypatch.setattr(worker_main, "get_platform_runtime", lambda *_args: runtime)
    monkeypatch.setattr(worker_main, "configure_json_logging", lambda: None)
    # The shared environment may disable the workers for the API: the worker turns them on regardless.
    monkeypatch.setenv(DISABLE_BACKGROUND_WORKERS_ENV, "1")
    # setenv, not delenv: the worker writes these into os.environ, and monkeypatch restores only what it set
    monkeypatch.setenv(SKIP_CHAT_BUILD_ENV, "0")
    monkeypatch.setenv(SKIP_IMAGE_PLUGINS_ENV, "0")
    monkeypatch.setenv(worker_main.HEALTH_PORT_ENV, "0")
    monkeypatch.setenv(worker_main.HEALTH_HOST_ENV, "127.0.0.1")
    stop = asyncio.Event()
    ready: asyncio.Future = asyncio.get_running_loop().create_future()

    main = asyncio.create_task(
        worker_main.main_async(stop_event=stop, on_ready=ready.set_result, install_signal_handlers=False)
    )
    health = await asyncio.wait_for(ready, timeout=5)
    import os

    assert runtime.started is True
    assert os.environ[DISABLE_BACKGROUND_WORKERS_ENV] == "0"
    assert os.environ[SKIP_CHAT_BUILD_ENV] == "1"
    assert await _get(health.port, "/livez") == (200, {"status": "alive", "role": "worker"})
    status, body = await _get(health.port, "/health")
    assert (status, body["status"]) == (200, "ok")
    assert (await _get(health.port, "/api/v1/sessions"))[0] == 404  # no API route is served

    runtime.task_scheduler._queue_dispatch_task.set_result(None)  # the dispatcher stopped
    status, body = await _get(health.port, "/health")
    assert (status, body["status"], body["checks"]["task_queue_dispatcher"]) == (503, "degraded", False)

    stop.set()
    await asyncio.wait_for(main, timeout=5)
    assert runtime.stopped is True


def test_worker_health_reports_starting_until_ready() -> None:
    assert worker_main.worker_health(_HealthRuntime(), phase="starting") == (
        503, {"status": "starting", "role": "worker"})
    assert worker_main.health_port({}) == worker_main.DEFAULT_HEALTH_PORT
    assert worker_main.health_port({worker_main.HEALTH_PORT_ENV: "off"}) is None
    assert worker_main.health_port({worker_main.HEALTH_PORT_ENV: "9101"}) == 9101


def test_api_worker_count_parses_a_positive_integer() -> None:
    assert api_worker_count(env={}) == 1
    assert api_worker_count(env={API_WORKERS_ENV: " 4 "}) == 4
    for bad in ("0", "-2", "two"):
        with pytest.raises(ValueError):
            api_worker_count(env={API_WORKERS_ENV: bad})


def test_main_passes_the_api_worker_count_to_uvicorn(monkeypatch) -> None:
    import app.main as app_main

    calls: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(app_main.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    monkeypatch.delenv(API_WORKERS_ENV, raising=False)
    app_main.main()
    assert "workers" not in calls[-1][1]
    assert calls[-1][1]["reload"] is app_main.settings.debug

    monkeypatch.setenv(API_WORKERS_ENV, "3")
    monkeypatch.setenv(DISABLE_BACKGROUND_WORKERS_ENV, "1")
    app_main.main()
    args, kwargs = calls[-1]
    assert args == ("app.main:app",)
    assert (kwargs["workers"], kwargs["reload"]) == (3, False)
    assert kwargs["proxy_headers"] is False  # forwarded headers stay untrusted

    # Several API processes would each run the scheduler, dispatcher and intake pollers: refused.
    monkeypatch.delenv(DISABLE_BACKGROUND_WORKERS_ENV)
    calls.clear()
    with pytest.raises(SystemExit, match="OCTRYX_DISABLE_BACKGROUND_WORKERS=1"):
        app_main.main()
    assert calls == []


@pytest.mark.asyncio
async def test_startup_lock_is_a_postgres_transaction_advisory_lock() -> None:
    from app.db.startup import STARTUP_ADVISORY_LOCK_KEY, cross_process_startup_lock

    statements: list[tuple[str, dict]] = []

    class _Conn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def begin(self):
            return self

        async def execute(self, statement, params):
            statements.append((str(statement), params))

    postgres = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), connect=lambda: _Conn())
    async with cross_process_startup_lock(postgres):
        assert statements == [("SELECT pg_advisory_xact_lock(:key)", {"key": STARTUP_ADVISORY_LOCK_KEY})]

    sqlite = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"), connect=lambda: pytest.fail("no lock"))
    async with cross_process_startup_lock(sqlite):
        pass
