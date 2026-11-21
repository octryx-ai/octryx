"""Tests for task queue entry recovery service (R-9)."""

import uuid
from datetime import timedelta

import pytest

from app.models import TaskQueueEntry
from app.services.worker_pool.task_queue_recovery_service import (
    claim_task_queue_entry,
    heartbeat_task_queue_entry,
    recover_stale_task_queue_entries,
    release_task_queue_entry,
)


@pytest.mark.asyncio
async def test_heartbeat_task_queue_entry_success(db):
    entry = TaskQueueEntry(
        id=str(uuid.uuid4()),
        task_run_id=str(uuid.uuid4()),
        task_type="scheduled_task",
        status="in_progress",
        assigned_to="worker-1",
    )
    db.add(entry)
    await db.commit()

    result = await heartbeat_task_queue_entry(db, entry.id, worker_id="worker-1")
    assert result is True
    assert entry.last_heartbeat is not None


@pytest.mark.asyncio
async def test_heartbeat_task_queue_entry_wrong_worker(db):
    entry = TaskQueueEntry(
        id=str(uuid.uuid4()),
        task_run_id=str(uuid.uuid4()),
        task_type="scheduled_task",
        status="in_progress",
        assigned_to="worker-1",
    )
    db.add(entry)
    await db.commit()

    result = await heartbeat_task_queue_entry(db, entry.id, worker_id="worker-2")
    assert result is False


@pytest.mark.asyncio
async def test_claim_task_queue_entry_success(db):
    entry = TaskQueueEntry(
        id=str(uuid.uuid4()),
        task_run_id=str(uuid.uuid4()),
        task_type="scheduled_task",
        status="pending",
    )
    db.add(entry)
    await db.commit()

    claimed = await claim_task_queue_entry(db, entry.id, worker_id="worker-1")
    assert claimed is True
    assert entry.status == "in_progress"
    assert entry.assigned_to == "worker-1"
    assert entry.last_heartbeat is not None
    assert entry.attempt_count == 1


@pytest.mark.asyncio
async def test_claim_task_queue_entry_already_assigned(db):
    entry = TaskQueueEntry(
        id=str(uuid.uuid4()),
        task_run_id=str(uuid.uuid4()),
        task_type="scheduled_task",
        status="pending",
        assigned_to="worker-1",
    )
    db.add(entry)
    await db.commit()

    claimed = await claim_task_queue_entry(db, entry.id, worker_id="worker-2")
    assert claimed is False


@pytest.mark.asyncio
async def test_claim_task_queue_entry_wrong_status(db):
    entry = TaskQueueEntry(
        id=str(uuid.uuid4()),
        task_run_id=str(uuid.uuid4()),
        task_type="scheduled_task",
        status="in_progress",
        assigned_to="worker-1",
    )
    db.add(entry)
    await db.commit()

    claimed = await claim_task_queue_entry(db, entry.id, worker_id="worker-2")
    assert claimed is False


@pytest.mark.asyncio
async def test_release_task_queue_entry_success(db):
    entry = TaskQueueEntry(
        id=str(uuid.uuid4()),
        task_run_id=str(uuid.uuid4()),
        task_type="scheduled_task",
        status="in_progress",
        assigned_to="worker-1",
    )
    db.add(entry)
    await db.commit()

    released = await release_task_queue_entry(db, entry.id, worker_id="worker-1", success=True)
    assert released is True
    assert entry.status == "completed"
    assert entry.completed_at is not None


@pytest.mark.asyncio
async def test_release_task_queue_entry_wrong_worker(db):
    entry = TaskQueueEntry(
        id=str(uuid.uuid4()),
        task_run_id=str(uuid.uuid4()),
        task_type="scheduled_task",
        status="in_progress",
        assigned_to="worker-1",
    )
    db.add(entry)
    await db.commit()

    released = await release_task_queue_entry(db, entry.id, worker_id="worker-2", success=False)
    assert released is False


@pytest.mark.asyncio
async def test_recover_stale_task_queue_entries(db):
    from app.time_utils import utc_now
    now = utc_now()

    # Stale entry
    stale_entry = TaskQueueEntry(
        id=str(uuid.uuid4()),
        task_run_id=str(uuid.uuid4()),
        task_type="scheduled_task",
        status="in_progress",
        assigned_to="worker-dead",
        last_heartbeat=now - timedelta(minutes=60),
    )
    db.add(stale_entry)

    # Fresh entry
    fresh_entry = TaskQueueEntry(
        id=str(uuid.uuid4()),
        task_run_id=str(uuid.uuid4()),
        task_type="scheduled_task",
        status="in_progress",
        assigned_to="worker-alive",
        last_heartbeat=now - timedelta(minutes=5),
    )
    db.add(fresh_entry)
    await db.commit()

    count = await recover_stale_task_queue_entries(db)
    assert count >= 1
    assert stale_entry.status == "pending"
    assert stale_entry.assigned_to is None
    assert stale_entry.last_heartbeat is None
    assert fresh_entry.status == "in_progress"


@pytest.mark.asyncio
async def test_recover_stale_task_queue_entries_no_heartbeat(db):
    entry = TaskQueueEntry(
        id=str(uuid.uuid4()),
        task_run_id=str(uuid.uuid4()),
        task_type="scheduled_task",
        status="in_progress",
        assigned_to="worker-dead",
        last_heartbeat=None,
    )
    db.add(entry)
    await db.commit()

    count = await recover_stale_task_queue_entries(db)
    assert count >= 1


@pytest.mark.asyncio
async def test_recover_stale_task_queue_entries_none_stale(db):
    from app.time_utils import utc_now
    entry = TaskQueueEntry(
        id=str(uuid.uuid4()),
        task_run_id=str(uuid.uuid4()),
        task_type="scheduled_task",
        status="in_progress",
        assigned_to="worker-1",
        last_heartbeat=utc_now() - timedelta(minutes=5),
    )
    db.add(entry)
    await db.commit()

    count = await recover_stale_task_queue_entries(db)
    assert count == 0
