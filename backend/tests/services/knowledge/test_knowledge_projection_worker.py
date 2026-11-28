from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import BackgroundWorkerRunState
from app.models.project.knowledge_evidence import (
    DEFAULT_MAX_PROJECTION_ATTEMPTS,
    OUTBOX_STATE_APPLIED,
    OUTBOX_STATE_DEAD_LETTER,
    OUTBOX_STATE_PENDING,
    PROJECTION_FAILURE_NOT_CONFIGURED,
    PROJECTION_FAILURE_UNAVAILABLE,
    KnowledgeProjectionOutboxEntry,
)
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.evidence_index.errors import EvidenceIndexUnavailableError
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from app.services.knowledge.ledger.errors import EvidenceStoreNotConfiguredError
from app.services.knowledge.projection.outbox import claim_next
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.projection.worker import MAX_ENTRIES_PER_TICK, WORKER_NAME, KnowledgeProjectionWorker
from app.time_utils import utc_now
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.support.knowledge_evidence_index_support import FakeEvidenceIndex


class _SelectiveUnavailableIndex(FakeEvidenceIndex):
    def __init__(self) -> None:
        super().__init__()
        self.unavailable_workspaces: set[str] = set()

    async def run(self, workspace, operation_key, parameters=None):
        if workspace.canonical in self.unavailable_workspaces:
            raise EvidenceIndexUnavailableError()
        return await super().run(workspace, operation_key, parameters)


def _session_factory(db: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)


async def _authorized_workspace(db: AsyncSession):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(
        db,
        current_user=await fetch_user(db, user_id),
        workspace_id=workspace_id,
        require_author=True,
    )
    return workspace_id, authorized


async def _ingest(db: AsyncSession, runtime, authorized, *, source_key: str) -> str:
    result = await ingest_text_source(
        db,
        runtime=runtime,
        authorized=authorized,
        source_key=source_key,
        display_title=source_key,
        declared_media_type="text/plain",
        data=f"Evidence for {source_key}.".encode(),
        created_by=None,
    )
    return result.revision_id


@pytest.mark.asyncio
async def test_tick_drains_two_workspaces_without_http_and_respects_fixed_bound(db):
    runtime, _, evidence_index = build_runtime()
    first_id, first = await _authorized_workspace(db)
    second_id, second = await _authorized_workspace(db)

    revision_ids = []
    for index in range(MAX_ENTRIES_PER_TICK + 1):
        authorized = first if index % 2 == 0 else second
        revision_ids.append(await _ingest(db, runtime, authorized, source_key=f"source-{index}"))

    worker = KnowledgeProjectionWorker(
        _session_factory(db),
        runtime_provider=lambda: runtime,
        worker_id="projection:test-bounded",
    )
    assert await worker.run_tick() == MAX_ENTRIES_PER_TICK

    db.expire_all()
    rows = (
        (
            await db.execute(
                select(KnowledgeProjectionOutboxEntry).where(
                    KnowledgeProjectionOutboxEntry.revision_id.in_(revision_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    assert sum(row.state == OUTBOX_STATE_APPLIED for row in rows) == MAX_ENTRIES_PER_TICK
    assert sum(row.state == OUTBOX_STATE_PENDING for row in rows) == 1
    assert {row.project_id for row in rows if row.state == OUTBOX_STATE_APPLIED} == {first_id, second_id}

    assert await worker.run_tick() == 1
    run_state = await db.get(BackgroundWorkerRunState, WORKER_NAME)
    assert run_state is not None
    assert run_state.status == "success"
    assert run_state.processed_count == 1
    assert run_state.error is None


@pytest.mark.asyncio
async def test_unavailable_entry_backs_off_dead_letters_and_does_not_block_healthy_work(db):
    evidence_index = _SelectiveUnavailableIndex()
    runtime, _, _ = build_runtime(index=evidence_index)
    bad_id, bad = await _authorized_workspace(db)
    _, healthy = await _authorized_workspace(db)
    evidence_index.unavailable_workspaces.add(bad.workspace.canonical)

    bad_revision = await _ingest(db, runtime, bad, source_key="unavailable-source")
    healthy_revision = await _ingest(db, runtime, healthy, source_key="healthy-source")
    worker = KnowledgeProjectionWorker(
        _session_factory(db),
        runtime_provider=lambda: runtime,
        worker_id="projection:test-retry",
    )

    assert await worker.run_tick() == 2
    db.expire_all()
    entries = {
        row.revision_id: row
        for row in (
            (
                await db.execute(
                    select(KnowledgeProjectionOutboxEntry).where(
                        KnowledgeProjectionOutboxEntry.revision_id.in_((bad_revision, healthy_revision))
                    )
                )
            )
            .scalars()
            .all()
        )
    }
    assert entries[healthy_revision].state == OUTBOX_STATE_APPLIED
    assert entries[bad_revision].state == OUTBOX_STATE_PENDING
    assert entries[bad_revision].attempt_count == 1
    assert entries[bad_revision].last_failure == PROJECTION_FAILURE_UNAVAILABLE
    assert entries[bad_revision].next_attempt_at > utc_now()

    assert await worker.run_tick() == 0
    await db.refresh(entries[bad_revision])
    assert entries[bad_revision].attempt_count == 1

    for expected_attempt in range(2, DEFAULT_MAX_PROJECTION_ATTEMPTS + 1):
        await db.execute(
            update(KnowledgeProjectionOutboxEntry)
            .where(
                KnowledgeProjectionOutboxEntry.project_id == bad_id,
                KnowledgeProjectionOutboxEntry.revision_id == bad_revision,
            )
            .values(next_attempt_at=utc_now() - timedelta(seconds=1))
        )
        await db.commit()
        assert await worker.run_tick() == 1
        await db.refresh(entries[bad_revision])
        assert entries[bad_revision].attempt_count == expected_attempt

    assert entries[bad_revision].state == OUTBOX_STATE_DEAD_LETTER
    assert entries[bad_revision].last_failure == PROJECTION_FAILURE_UNAVAILABLE


@pytest.mark.asyncio
async def test_stop_waits_for_in_flight_turn_and_prevents_another_claim(db, monkeypatch):
    runtime, _, evidence_index = build_runtime()
    _, authorized = await _authorized_workspace(db)
    revision_id = await _ingest(db, runtime, authorized, source_key="stop-source")
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def blocking_project_once(self, db, *, worker_id, project_id=None):
        nonlocal calls
        calls += 1
        claimed = await claim_next(db, worker_id=worker_id, project_id=project_id)
        assert claimed is not None
        entered.set()
        await release.wait()
        return await self.apply_claimed(db, claimed)

    monkeypatch.setattr(EvidenceProjector, "project_once", blocking_project_once)
    worker = KnowledgeProjectionWorker(
        _session_factory(db),
        runtime_provider=lambda: runtime,
        poll_interval_seconds=0.01,
        worker_id="projection:test-stop",
    )

    await worker.start()
    await asyncio.wait_for(entered.wait(), timeout=1)
    stopping = asyncio.create_task(worker.stop())
    await asyncio.sleep(0)
    assert stopping.done() is False
    assert calls == 1

    release.set()
    await asyncio.wait_for(stopping, timeout=1)
    assert calls == 1
    assert worker.running is False
    db.expire_all()
    entry = (
        await db.execute(
            select(KnowledgeProjectionOutboxEntry).where(
                KnowledgeProjectionOutboxEntry.revision_id == revision_id
            )
        )
    ).scalar_one()
    assert entry.state == OUTBOX_STATE_APPLIED
    assert entry.claimed_until is None


@pytest.mark.asyncio
async def test_unconfigured_runtime_idles_with_only_the_fixed_failure_token(db):
    def unconfigured_runtime():
        raise EvidenceStoreNotConfiguredError()

    first = KnowledgeProjectionWorker(
        _session_factory(db),
        runtime_provider=unconfigured_runtime,
        worker_id="projection:test-unconfigured",
    )
    second = KnowledgeProjectionWorker(_session_factory(db), runtime_provider=unconfigured_runtime)

    assert await first.run_tick() == 0
    row = await db.get(BackgroundWorkerRunState, WORKER_NAME)
    assert row is not None
    assert row.status == "failed"
    assert row.error == PROJECTION_FAILURE_NOT_CONFIGURED
    assert row.details_json == {"result_type": "error"}
    assert row.owner == first.worker_id
    assert second.worker_id.startswith("projection:")
    assert second.worker_id != first.worker_id
    assert len(second.worker_id) <= 64


@pytest.mark.asyncio
async def test_a_transient_state_write_failure_does_not_kill_the_managed_task(db, monkeypatch, caplog):
    worker = KnowledgeProjectionWorker(
        _session_factory(db),
        poll_interval_seconds=0.01,
        worker_id="projection:test-loop-recovery",
    )
    recovered = asyncio.Event()
    calls = 0

    async def flaky_tick():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("secret-bearing dependency detail")
        recovered.set()
        worker._stop_event.set()
        return 0

    monkeypatch.setattr(worker, "run_tick", flaky_tick)

    await worker.start()
    await asyncio.wait_for(recovered.wait(), timeout=1)
    await worker.stop()

    assert calls == 2
    assert worker.running is False
    assert "secret-bearing dependency detail" not in caplog.text
    assert "outside its fixed contract" in caplog.text
