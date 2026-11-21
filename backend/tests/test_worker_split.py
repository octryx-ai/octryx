"""Background workers in their own process, the API in one or several processes.

Covers the role split of ``PlatformRuntime.startup``, the worker entrypoint with its probe port,
``OCTRYX_API_WORKERS`` in ``main()``, the cross-process startup lock and channel placement.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.runtime_setup as runtime_setup
from app.runtime_setup import PlatformRuntime
from app.runtime_toggles import DISABLE_BACKGROUND_WORKERS_ENV
from tests.worker_split_support import _FakeDb


class _Worker:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self._task = None

    async def start(self, *args) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    def is_running(self) -> bool:
        return self.started and not self.stopped


class _Scheduler(_Worker):
    def __init__(self) -> None:
        super().__init__()
        self.shutdown_called = False
        self._queue_dispatch_task = None

    def shutdown(self) -> None:
        self.shutdown_called = True

    def set_session_factory(self, session_factory) -> None:
        self.session_factory = session_factory


class _Router(_Worker):
    async def start(self, session_factory) -> None:
        self.started = True


class _Reconciler(_Worker):
    def __init__(self) -> None:
        super().__init__()
        self.reconciled = 0

    async def reconcile_once(self):
        self.reconciled += 1
        return {}


class _Flusher:
    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False


def _runtime() -> PlatformRuntime:
    names = (
        "retention_worker notification_delivery_worker outbound_webhook_worker connector_health_worker "
        "analytics_worker knowledge_projection_worker worker_monitor_worker worker_agenda_worker "
        "worker_report_worker worker_pool_worker sla_monitor_worker secret_expiry_worker "
        "session_workspace_cleanup_worker runtime_ownership_worker knowledge_source_sync_scheduler "
        "stale_approval_expiry_worker workflow_run_sweep_worker "
        "workflow_run_watch_worker pull_request_refresh_worker workflow_run_review_worker "
        "skill_upstream_worker change_source_poll_worker remote_stop_watcher"
    ).split()
    return PlatformRuntime(
        async_session_factory=_FakeDb,
        task_scheduler=_Scheduler(),
        channel_reconciler=_Reconciler(),
        **{name: _Worker() for name in names},
    )


_ALWAYS_ON = {"runtime_ownership_worker", "remote_stop_watcher"}


def _background_workers(runtime: PlatformRuntime) -> dict[str, _Worker]:
    workers = {
        name: getattr(runtime, name)
        for name in runtime.__dataclass_fields__
        if isinstance(getattr(runtime, name, None), _Worker)
        and not isinstance(getattr(runtime, name), _Reconciler)
        and name not in _ALWAYS_ON
    }
    workers["task_scheduler"] = runtime.task_scheduler
    return workers


@pytest.fixture
def startup_seams(monkeypatch):
    router, prefetch, flusher = _Router(), _Worker(), _Flusher()
    monkeypatch.setattr(runtime_setup, "channel_message_router", router)
    monkeypatch.setattr(runtime_setup, "prefetch_worker", prefetch)
    monkeypatch.setattr(runtime_setup, "decision_flusher", flusher)
    monkeypatch.setattr(runtime_setup, "ensure_chat_frontend_built", lambda: None)

    async def _ready(*args, **kwargs):
        return None

    async def _refresh(db):
        return 0

    monkeypatch.setattr(runtime_setup, "ensure_runtime_database_ready", _ready)
    monkeypatch.setattr(runtime_setup, "refresh_all_workers_on_startup", _refresh)
    monkeypatch.setenv("OCTRYX_ENABLE_KNOWLEDGE_SOURCE_SYNC_SCHEDULER", "1")
    return SimpleNamespace(router=router, prefetch=prefetch, flusher=flusher)


@pytest.mark.asyncio
async def test_api_startup_with_background_workers_disabled_starts_none_of_them(monkeypatch, startup_seams) -> None:
    monkeypatch.setenv(DISABLE_BACKGROUND_WORKERS_ENV, "1")
    runtime = _runtime()

    await runtime.startup()

    started = sorted(name for name, worker in _background_workers(runtime).items() if worker.started)
    assert started == []
    assert startup_seams.prefetch.started is False
    # What every process runs: its liveness lease, the remote stop watcher and its channels.
    assert runtime.runtime_ownership_worker.started is True
    assert runtime.remote_stop_watcher.started is True
    assert runtime.channel_reconciler.reconciled == 1 and runtime.channel_reconciler.started is True
    assert startup_seams.router.started is True

    await runtime.shutdown()
    assert runtime.remote_stop_watcher.stopped is True
    assert runtime.channel_reconciler.stopped is True
    assert startup_seams.router.stopped is True
    assert not any(worker.stopped for worker in _background_workers(runtime).values())


@pytest.mark.asyncio
async def test_startup_with_background_workers_enabled_starts_all_of_them(monkeypatch, startup_seams) -> None:
    monkeypatch.delenv(DISABLE_BACKGROUND_WORKERS_ENV, raising=False)
    runtime = _runtime()

    await runtime.startup()

    not_started = sorted(name for name, worker in _background_workers(runtime).items() if not worker.started)
    assert not_started == []
    assert startup_seams.prefetch.started is True
    await runtime.shutdown()
    assert all(worker.stopped or name == "task_scheduler" for name, worker in _background_workers(runtime).items())
    assert runtime.task_scheduler.shutdown_called is True
