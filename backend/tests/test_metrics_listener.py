"""The internal ``/metrics`` listener: no authentication, its own port, off unless ``OCTRYX_METRICS_PORT``.

On a local stack Prometheus scrapes the api and the worker in the private compose
network with no API key. The authenticated ``/metrics`` on the api port is unchanged (``test_auth``).
"""

from __future__ import annotations

import asyncio
import socket

import pytest

import app.main as api_main
import app.worker_main as worker_main
from app.runtime_toggles import (
    API_WORKERS_ENV,
    DISABLE_BACKGROUND_WORKERS_ENV,
    SKIP_CHAT_BUILD_ENV,
    SKIP_IMAGE_PLUGINS_ENV,
)
from app.services.observability import metrics_listener
from app.services.observability.metrics_listener import (
    METRICS_HOST_ENV,
    METRICS_PORT_ENV,
    MetricsListener,
    metrics_port,
    start_metrics_listener,
)

BODY = "# TYPE octryx_example_total counter\noctryx_example_total 3\n"


async def _request(port: int, raw: bytes) -> tuple[int, bytes, bytes]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(raw)
    await writer.drain()
    answer = await reader.read()
    writer.close()
    head, _, body = answer.partition(b"\r\n\r\n")
    return int(head.split()[1]), head, body


def _get(path: str, method: str = "GET") -> bytes:
    return f"{method} {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode()


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def _render() -> str:
    return BODY


def test_the_listener_is_off_unless_its_port_is_set() -> None:
    assert metrics_port({}) is None
    assert metrics_port({METRICS_PORT_ENV: " off "}) is None
    assert metrics_port({METRICS_PORT_ENV: "9464"}) == 9464
    with pytest.raises(ValueError):
        metrics_port({METRICS_PORT_ENV: "70000"})


@pytest.mark.asyncio
async def test_unset_port_starts_nothing() -> None:
    assert await start_metrics_listener(_render, role="api", env={}) is None


@pytest.mark.asyncio
async def test_metrics_need_no_credential_and_nothing_else_is_served() -> None:
    listener = await start_metrics_listener(
        _render, role="api", env={METRICS_PORT_ENV: "0", METRICS_HOST_ENV: "127.0.0.1"})
    assert listener is not None
    try:
        status, head, body = await _request(listener.port, _get("/metrics"))
        assert (status, body.decode()) == (200, BODY)
        assert b"text/plain; version=0.0.4" in head
        status, _, body = await _request(listener.port, _get("/metrics", "HEAD"))
        assert (status, body) == (200, b"")
        assert (await _request(listener.port, _get("/api/v1/sessions")))[0] == 404
        assert (await _request(listener.port, _get("/health")))[0] == 404
        assert (await _request(listener.port, _get("/metrics", "POST")))[0] == 405
        assert (await _request(listener.port, b"garbage\r\n\r\n"))[0] == 400
    finally:
        await listener.stop()


@pytest.mark.asyncio
async def test_a_failed_render_is_a_500_and_the_listener_keeps_serving() -> None:
    calls = []

    async def flaky() -> str:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("render failed")
        return BODY

    listener = MetricsListener(flaky, host="127.0.0.1", port=0, role="worker")
    await listener.start()
    try:
        assert (await _request(listener.port, _get("/metrics")))[0] == 500
        assert (await _request(listener.port, _get("/metrics")))[0] == 200
    finally:
        await listener.stop()


@pytest.mark.asyncio
async def test_the_worker_serves_its_counters_on_the_metrics_port(monkeypatch) -> None:
    class Runtime:
        started = stopped = False

        async def startup(self) -> None:
            self.started = True

        async def shutdown(self) -> None:
            self.stopped = True

    async def worker_metrics(_factory) -> str:
        return BODY

    port = _free_port()
    monkeypatch.setattr(worker_main, "get_platform_runtime", lambda *_args: Runtime())
    monkeypatch.setattr(worker_main, "configure_json_logging", lambda: None)
    monkeypatch.setattr("app.services.observability.metrics_render.render_worker_metrics", worker_metrics)
    monkeypatch.setenv(worker_main.HEALTH_PORT_ENV, "off")
    monkeypatch.setenv(METRICS_PORT_ENV, str(port))
    monkeypatch.setenv(METRICS_HOST_ENV, "127.0.0.1")
    # the worker writes its role flags into os.environ; set them first so monkeypatch restores them afterwards
    for name, value in ((DISABLE_BACKGROUND_WORKERS_ENV, "1"), (SKIP_CHAT_BUILD_ENV, "0"), (SKIP_IMAGE_PLUGINS_ENV, "0")):
        monkeypatch.setenv(name, value)
    stop = asyncio.Event()
    ready: asyncio.Future = asyncio.get_running_loop().create_future()
    main = asyncio.create_task(
        worker_main.main_async(stop_event=stop, on_ready=ready.set_result, install_signal_handlers=False))
    await asyncio.wait_for(ready, timeout=5)
    try:
        status, _, body = await _request(port, _get("/metrics"))
        assert (status, body.decode()) == (200, BODY)
    finally:
        stop.set()
        await asyncio.wait_for(main, timeout=5)
    with pytest.raises(OSError):  # closed on shutdown
        await _request(port, _get("/metrics"))


@pytest.mark.asyncio
async def test_the_api_starts_the_listener_only_as_its_single_process(monkeypatch) -> None:
    started: list[str] = []

    async def fake_start(render, *, role, env=None):
        started.append(role)
        return None

    monkeypatch.setattr(api_main, "start_metrics_listener", fake_start)
    monkeypatch.setenv(METRICS_PORT_ENV, "9464")
    monkeypatch.delenv(API_WORKERS_ENV, raising=False)
    from contextlib import AsyncExitStack

    async with AsyncExitStack() as stack:
        await api_main._start_internal_metrics(stack)
    assert started == ["api"]

    monkeypatch.setenv(API_WORKERS_ENV, "2")
    async with AsyncExitStack() as stack:
        await api_main._start_internal_metrics(stack)
    assert started == ["api"]  # several api processes: off

    monkeypatch.delenv(API_WORKERS_ENV, raising=False)
    monkeypatch.delenv(METRICS_PORT_ENV, raising=False)
    async with AsyncExitStack() as stack:
        await api_main._start_internal_metrics(stack)
    assert started == ["api"]  # unset: off


def test_the_default_host_is_all_interfaces_of_the_namespace() -> None:
    assert metrics_listener.DEFAULT_METRICS_HOST == "0.0.0.0"  # noqa: S104 - the deployment keeps the port private
