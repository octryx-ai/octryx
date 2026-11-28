from __future__ import annotations

import asyncio
import dataclasses

import pytest

import app.runtime_setup as runtime_setup
from app.db import core as db_core
from app.runtime_toggles import DISABLE_BACKGROUND_WORKERS_ENV, SKIP_IMAGE_PLUGINS_ENV
from app.services.data_access import PlatformMaintenance, ViewerNotSetError, current_viewer, request_scope
from app.services.knowledge.retention.scheduled import RECONCILE_REASON
from tests.conftest import shared_test_session_factory

TICK_SECONDS = 60
STOP_SECONDS = 30
# Workers whose run reads under a maintenance reason of their own (pinned in _data_viewer_allowlist), besides the
# workers' reason they start under.
OWN_REASONS = {"knowledge_retention_reconcile_worker": {RECONCILE_REASON}}


def _loop_tasks(runtime) -> dict[str, asyncio.Task]:
    fields = {field.name: getattr(runtime, field.name) for field in dataclasses.fields(runtime)}
    tasks = {name: task for name, value in fields.items()
             for attribute in ("_task", "task", "_loop_task")
             if isinstance(task := getattr(value, attribute, None), asyncio.Task)}
    if isinstance(runtime._health_loop_task, asyncio.Task):
        tasks["health_loop"] = runtime._health_loop_task
    return tasks


@pytest.mark.committed_db
@pytest.mark.timeout(120)
async def test_the_runtime_workers_read_as_the_pinned_maintenance_and_hit_no_viewer_error(db, monkeypatch):
    monkeypatch.setenv(DISABLE_BACKGROUND_WORKERS_ENV, "0")
    monkeypatch.setenv(SKIP_IMAGE_PLUGINS_ENV, "1")
    monkeypatch.setattr(runtime_setup, "ensure_chat_frontend_built", lambda: None)

    async def _schema_ready(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(runtime_setup, "ensure_runtime_database_ready", _schema_ready)
    monkeypatch.setattr(db_core, "async_session_factory", shared_test_session_factory)
    raised: list[str] = []
    original_init = ViewerNotSetError.__init__

    def recording_init(self, tables):
        raised.append(", ".join(sorted(tables)))
        original_init(self, tables)

    monkeypatch.setattr(ViewerNotSetError, "__init__", recording_init)
    runtime = runtime_setup.build_platform_runtime(shared_test_session_factory)
    ticked = asyncio.Event()
    checks: dict = {}
    original_checks = runtime_setup.PlatformRuntime.health_checks

    async def health_checks(self, **kwargs):
        checks.update(await original_checks(self, **kwargs))
        ticked.set()
        return checks

    monkeypatch.setattr(runtime_setup.PlatformRuntime, "health_checks", health_checks)
    try:
        with request_scope():  # the API's lifespan and the worker's main start with no viewer
            await asyncio.wait_for(runtime.startup(), TICK_SECONDS)
        await asyncio.wait_for(ticked.wait(), TICK_SECONDS)
        tasks = _loop_tasks(runtime)
        assert "connector_health_worker" in tasks and "health_loop" in tasks
        for name, task in tasks.items():
            viewer = task.get_context().run(current_viewer)
            reasons = {runtime_setup.WORKERS_REASON, *OWN_REASONS.get(name, ())}
            assert isinstance(viewer, PlatformMaintenance) and viewer.reason in reasons, name
        with request_scope():  # an /api/v1/health call: no viewer
            probe = await asyncio.wait_for(original_checks(runtime, app_version=""), TICK_SECONDS)
    finally:
        await asyncio.wait_for(runtime.shutdown(), STOP_SECONDS)
    assert raised == []
    assert "without a data viewer" not in str(checks) + str(probe)
    connector = probe["checks"]["connector_health_worker"]
    assert connector["status"] != "error", connector
