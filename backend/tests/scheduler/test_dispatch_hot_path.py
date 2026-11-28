"""The queue dispatcher's 0.75 s tick stays cheap, and the hot-path indexes exist in models and migration."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models import AuditLog, DeviceJobApproval, KnowledgeSourceHead, TaskRun
from app.scheduler.dispatch import backend as dispatch_backend
from app.scheduler.dispatch.backend import REDIS_QUEUE_URLS_TTL_SECONDS, SchedulerDispatchBackendMixin
from app.services.worker_pool.state import mark_worker_pool_config_changed


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def scalars(self):
        return self


class _FakeDb:
    def __init__(self, *results):
        self.results = list(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(str(statement))
        return _Result(self.results.pop(0) if self.results else [])


class _Dispatcher(SchedulerDispatchBackendMixin):
    pass


@pytest.fixture
def clock(monkeypatch):
    now = {"value": 1000.0}
    monkeypatch.setattr(dispatch_backend.time, "monotonic", lambda: now["value"])
    return now


async def test_the_redis_queue_urls_are_read_once_per_interval(clock):
    dispatcher = _Dispatcher()
    db = _FakeDb([("redis://queue-a",), ("",)], [("redis://queue-b",)])

    assert await dispatcher._configured_redis_queue_urls(db) == ["redis://queue-a"]
    clock["value"] += REDIS_QUEUE_URLS_TTL_SECONDS - 1
    assert await dispatcher._configured_redis_queue_urls(db) == ["redis://queue-a"]
    assert len(db.statements) == 1
    assert "worker_pool_config" in db.statements[0]

    clock["value"] += 2
    assert await dispatcher._configured_redis_queue_urls(db) == ["redis://queue-b"]
    assert len(db.statements) == 2


async def test_a_pool_config_change_in_this_process_applies_at_once(clock):
    dispatcher = _Dispatcher()
    db = _FakeDb([], [("redis://new",)])

    assert await dispatcher._configured_redis_queue_urls(db) == []
    mark_worker_pool_config_changed()
    assert await dispatcher._configured_redis_queue_urls(db) == ["redis://new"]
    assert len(db.statements) == 2


async def test_the_settings_fallback_url_is_still_added(clock, monkeypatch):
    import app.config as config_module

    monkeypatch.setattr(config_module, "get_settings", lambda: SimpleNamespace(redis_url="redis://fallback"))
    dispatcher = _Dispatcher()
    db = _FakeDb([("redis://fallback",), ("redis://queue-a",)])

    assert await dispatcher._list_active_redis_queue_urls(db) == ["redis://fallback", "redis://queue-a"]
    assert await dispatcher._list_active_redis_queue_urls(db) == ["redis://fallback", "redis://queue-a"]
    assert len(db.statements) == 1


async def test_an_idle_tick_reads_only_the_waiting_entries():
    db = _FakeDb([])

    await _Dispatcher()._refresh_queue_wait_estimates(db)

    assert len(db.statements) == 1
    assert "task_queue_entries" in db.statements[0]
    assert "ORDER BY task_runs.completed_at" not in db.statements[0]


async def test_waiting_entries_still_get_their_estimate():
    from datetime import timedelta

    from app.time_utils import utc_now

    finished = utc_now()
    runs = [SimpleNamespace(started_at=finished - timedelta(seconds=30), completed_at=finished)]
    first, second = SimpleNamespace(estimated_wait_seconds=None), SimpleNamespace(estimated_wait_seconds=None)
    running = [SimpleNamespace()]
    db = _FakeDb([first, second], runs, running)

    await _Dispatcher()._refresh_queue_wait_estimates(db)

    assert (first.estimated_wait_seconds, second.estimated_wait_seconds) == (30, 60)
    assert len(db.statements) == 3


HOT_PATH_INDEXES = {
    TaskRun: {
        "ix_task_runs_completed_at": ("completed_at",),
        "ix_task_runs_task_started": ("task_id", "started_at"),
        "ix_task_runs_status_started": ("status", "started_at"),
        "ix_task_runs_session_id": ("session_id",),
    },
    DeviceJobApproval: {
        "ix_device_job_approvals_owner_status_created": ("owner_user_id", "status", "created_at"),
    },
    AuditLog: {
        "ix_audit_log_user_action_created": ("user_id", "action", "created_at"),
        "ix_audit_log_action_resource_created": ("action", "resource_id", "created_at"),
    },
    KnowledgeSourceHead: {
        "ix_knowledge_source_heads_current_revision": ("current_revision_id",),
    },
}
