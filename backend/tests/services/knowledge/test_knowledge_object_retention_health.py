from __future__ import annotations

import contextlib

import pytest

from app.models import BackgroundWorkerRunState
from app.services.knowledge.retention import scheduled
from app.services.knowledge.retention.scheduled import WORKER_NAME, KnowledgeRetentionReconcileWorker
from app.services.observability.health_read_model import health_overview
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.services.knowledge.knowledge_object_retention_support import _set_policy, _wired

ROW = f"Worker {WORKER_NAME}"


def _worker(db, maintain) -> KnowledgeRetentionReconcileWorker:
    @contextlib.asynccontextmanager
    async def factory():
        yield db

    return KnowledgeRetentionReconcileWorker(factory, maintenance_factory=lambda: maintain)


async def _health_row(db) -> dict:
    payload = await health_overview(db, checks={})
    platform = next(group for group in payload["groups"] if group["key"] == "platform")["rows"]
    return next(item for item in platform if item["component"] == ROW)


async def _governed(db, count: int) -> list[str]:
    workspace_ids = sorted([await seed_workspace(db) for _ in range(count)])
    for workspace_id in workspace_ids:
        await _set_policy(db, workspace_id)
    return workspace_ids


@pytest.mark.asyncio
async def test_a_pass_where_every_workspace_failed_is_a_failing_worker(db):
    await _governed(db, 2)
    _runtime, maintain, object_client = _wired()
    object_client.unavailable = True

    outcome = await _worker(db, maintain).run_once()

    assert outcome["workspaces"] >= 2 and outcome["failed"] == outcome["workspaces"]
    state = await db.get(BackgroundWorkerRunState, WORKER_NAME)
    assert (state.status, state.failure_count) == ("failed", 1)
    row = await _health_row(db)
    assert row["status"] == "failing"
    assert row["detail"] == f"every Workspace failed reconciliation ({outcome['failed']} of {outcome['workspaces']})"


@pytest.mark.asyncio
async def test_a_partial_failure_is_degraded_and_shows_the_workspace_outcome_counts(db, monkeypatch):
    crashing, *_healthy = await _governed(db, 2)
    _runtime, maintain, _client = _wired()
    real = scheduled.reconcile_workspace

    async def flaky(db_, *, project_id, **kwargs):
        if project_id == crashing:
            raise RuntimeError("synthetic crash")
        return await real(db_, project_id=project_id, **kwargs)

    monkeypatch.setattr(scheduled, "reconcile_workspace", flaky)
    outcome = await _worker(db, maintain).run_once()

    assert outcome["failed"] == 1 and outcome["reconciled"] == outcome["workspaces"] - 1 >= 1
    row = await _health_row(db)
    assert row["status"] == "degraded"
    assert row["detail"] == (f"some Workspaces failed reconciliation · workspaces {outcome['workspaces']} · "
                             f"reconciled {outcome['reconciled']} · failed 1")


@pytest.mark.asyncio
async def test_a_clean_pass_is_ok(db):
    await _governed(db, 2)
    _runtime, maintain, _client = _wired()

    outcome = await _worker(db, maintain).run_once()

    assert outcome["failed"] == 0 and outcome["reconciled"] == outcome["workspaces"] >= 2
    state = await db.get(BackgroundWorkerRunState, WORKER_NAME)
    assert (state.status, state.failure_count) == ("success", 0)
    assert (await _health_row(db))["status"] == "ok"


@pytest.mark.asyncio
async def test_a_pass_without_a_knowledge_store_is_disabled_not_failing(db):
    await _governed(db, 1)
    worker = KnowledgeRetentionReconcileWorker(
        _worker(db, None)._session_factory, maintenance_factory=lambda: scheduled.maintenance_from_environment({}))

    await worker.run_once()

    row = await _health_row(db)
    assert row["status"] == "disabled" and row["detail"].startswith("not configured")
