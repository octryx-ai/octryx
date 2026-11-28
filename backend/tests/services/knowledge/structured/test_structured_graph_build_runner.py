"""Manual structured builds run in their own bounded runner, never behind the projection worker."""

from __future__ import annotations

import asyncio
import time

from sqlalchemy import select

from app.models import BackgroundWorkerRunState
from app.services.knowledge.ledger.errors import EvidenceStoreNotConfiguredError
from app.services.knowledge.projection.worker import KnowledgeProjectionWorker
from app.services.knowledge.structured import build_runner
from app.services.knowledge.structured.build import request_build
from app.services.knowledge.structured.build_runner import FAILURE_RUNTIME, RUNNER_NAME, StructuredBuildRunner
from app.services.knowledge.structured.build_states import (
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_RUNNING,
    TRIGGER_MANUAL,
    TRIGGER_SOURCE_SYNC,
)
from app.time_utils import utc_now
from tests.services.knowledge.structured.structured_graph_build_runner_support import (
    _factory,
    _reload,
    _runner,
    _workspace,
)


async def test_the_runner_completes_a_manual_build_in_short_slices_and_yields_between_them(db, monkeypatch):
    project_id = await _workspace(db)
    build = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    slices: list[dict] = []
    sleeps: list[float] = []
    real_slice, real_sleep = build_runner.run_build_slice, asyncio.sleep

    async def spy_slice(db, **kwargs):
        slices.append({key: kwargs[key] for key in ("budget_seconds", "max_revisions")})
        return await real_slice(db, **kwargs)

    async def spy_sleep(seconds):
        sleeps.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(build_runner, "run_build_slice", spy_slice)
    monkeypatch.setattr(build_runner.asyncio, "sleep", spy_sleep)
    monkeypatch.setattr(build_runner, "MAX_REVISIONS_PER_SLICE", 1)
    assert await _runner(db).run_once() == STATE_COMPLETED
    build = await _reload(db, build)
    assert build.state == STATE_COMPLETED and build.report["layers"]["manual"]["extracted"] == 2
    # One revision per slice here: two extraction slices and the linkage slice, each short.
    assert len(slices) == build.report["slices"] >= 2
    assert all(item == {"budget_seconds": build_runner.SLICE_SECONDS, "max_revisions": 1} for item in slices)
    assert sleeps == [build_runner.YIELD_SECONDS] * (len(slices) - 1)
    assert build_runner.SLICE_SECONDS <= 2.0


async def test_the_runner_leaves_source_sync_refreshes_to_the_projection_worker(db):
    project_id = await _workspace(db)
    build = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_SOURCE_SYNC)
    assert await _runner(db).run_once() is None
    assert (await _reload(db, build)).state == "pending"


async def test_a_manual_request_makes_a_pending_refresh_manual(db):
    project_id = await _workspace(db)
    refresh = await request_build(db, project_id=project_id, layers=["configuration"], trigger=TRIGGER_SOURCE_SYNC)
    manual = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    assert manual.id == refresh.id and manual.trigger == TRIGGER_MANUAL
    assert manual.layers == ["manual", "configuration"]
    again = await request_build(db, project_id=project_id, layers=["operations"], trigger=TRIGGER_SOURCE_SYNC)
    assert again.id == manual.id and again.trigger == TRIGGER_MANUAL


async def test_a_long_build_is_handed_back_after_its_run_budget_and_resumed(db, monkeypatch):
    project_id = await _workspace(db)
    build = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    monkeypatch.setattr(build_runner, "MAX_REVISIONS_PER_SLICE", 1)
    runner = _runner(db, max_run_seconds=0.0)
    assert await runner.run_once() == STATE_RUNNING
    handed = await _reload(db, build)
    assert handed.state == STATE_RUNNING and handed.claimed_by == runner.worker_id
    assert handed.lease_until <= utc_now().replace(tzinfo=handed.lease_until.tzinfo)
    states = [await runner.run_once() for _ in range(5)]
    assert STATE_COMPLETED in states
    assert (await _reload(db, build)).report["layers"]["manual"]["extracted"] == 2


async def test_a_raising_slice_fails_the_build_with_the_fixed_token(db, monkeypatch):
    project_id = await _workspace(db)
    build = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)

    async def broken(db, **kwargs):
        raise RuntimeError("postgres://user:secret@db")

    monkeypatch.setattr(build_runner, "run_build_slice", broken)
    assert await _runner(db).run_once() == STATE_FAILED
    failed = await _reload(db, build)
    assert failed.state == STATE_FAILED and failed.failure == "build_failed" and "secret" not in repr(failed.report)


async def test_the_runner_is_idle_without_an_evidence_runtime(db):
    project_id = await _workspace(db)
    build = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)

    def missing():
        raise EvidenceStoreNotConfiguredError()

    assert await StructuredBuildRunner(_factory(db), runtime_provider=missing).run_once() is None
    assert (await _reload(db, build)).state == "pending"
    state = (await db.execute(select(BackgroundWorkerRunState).where(
        BackgroundWorkerRunState.worker_name == RUNNER_NAME))).scalar_one()
    assert state.error == "not_configured", "no knowledge store is a choice, reported like the projection worker"


async def test_a_configured_runtime_that_fails_is_reported_as_unavailable(db):
    def broken():
        raise RuntimeError("store down")

    assert await StructuredBuildRunner(_factory(db), runtime_provider=broken).run_once() is None
    state = (await db.execute(select(BackgroundWorkerRunState).where(
        BackgroundWorkerRunState.worker_name == RUNNER_NAME))).scalar_one()
    assert state.error == FAILURE_RUNTIME


async def test_the_projection_worker_owns_the_runner_lifecycle(db):
    # No evidence runtime: both loops stay off the database, so the test session is never shared.
    calls: list[str] = []

    def missing():
        calls.append("runtime")
        raise EvidenceStoreNotConfiguredError()

    worker = KnowledgeProjectionWorker(_factory(db), runtime_provider=missing, poll_interval_seconds=0.05,
                                       worker_id="projection:test-runner")
    runner = worker._build_runner
    assert isinstance(runner, StructuredBuildRunner) and not runner.running
    await worker.start()
    try:
        assert runner.running
        deadline = time.monotonic() + 5
        while len(calls) < 2 and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
    finally:
        await worker.stop()
    assert not runner.running and not worker.running
