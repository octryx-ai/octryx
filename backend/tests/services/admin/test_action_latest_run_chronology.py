"""Contract: an Action's "last run" summary and its run history use one chronology."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.models import Project, Task, TaskQueueEntry, TaskRun, User
from app.services.admin.task._admin_task_management import list_task_runs
from app.services.admin.task._admin_task_stats import serialize_task_with_stats


def at(minute: int) -> datetime:
    return datetime(2026, 10, 4, 10, minute)


async def _task(db) -> tuple[Task, str, str]:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project))).scalars().first()
    task = Task(dispatch_binding="task_definition", name=f"chronology-{uuid.uuid4().hex[:6]}", owner_id=admin.id, project_id=project.id)
    db.add(task)
    await db.flush()
    return task, admin.id, project.id


async def _run(db, task, owner_id, project_id, *, run_id, status, started_at=None, queued_at=None, queue=True):
    run = TaskRun(id=run_id, task_id=task.id, status=status, started_by=owner_id, started_at=started_at)
    db.add(run)
    await db.flush()
    # As the enqueue path does (scheduler/dispatch/backend.py): the column default stamps "now" on
    # insert, so a not-yet-started run is cleared to NULL after the flush.
    run.started_at = started_at
    await db.flush()
    if queue:
        db.add(
            TaskQueueEntry(
                id=str(uuid.uuid4()),
                task_run_id=run.id,
                project_id=project_id,
                task_type="agent_run",
                priority=5,
                status="pending" if status == "queued" else "completed",
                queued_at=queued_at,
            )
        )
    return run


async def _agree(db, task) -> tuple[str, list[str], dict]:
    await db.commit()
    history = await list_task_runs(db, task_id=task.id)
    summary = await serialize_task_with_stats(db, task)
    first = history[0]
    assert summary["last_run_status"] == first["status"]
    assert summary["last_run_at"] == first["started_at"], "the summary reports the real start time, None if not started"
    assert summary["run_count"] == len(history)
    return first["id"], [row["id"] for row in history], summary


@pytest.mark.asyncio
async def test_a_later_queued_run_is_the_latest_even_when_neither_has_started(db):
    task, owner, project = await _task(db)
    await _run(db, task, owner, project, run_id="ffff-old", status="cancelled", queued_at=at(0))
    await _run(db, task, owner, project, run_id="0000-new", status="queued", queued_at=at(5))
    first, ids, summary = await _agree(db, task)
    assert (first, ids) == ("0000-new", ["0000-new", "ffff-old"]), "newer queue time wins over any id order"
    assert (summary["last_run_status"], summary["last_run_at"]) == ("queued", None), "no start time invented"


@pytest.mark.asyncio
async def test_a_started_run_and_a_queued_run_compare_by_their_effective_times(db):
    task, owner, project = await _task(db)
    await _run(db, task, owner, project, run_id="a-started", status="success", started_at=at(10), queued_at=at(1))
    await _run(db, task, owner, project, run_id="b-queued-earlier", status="queued", queued_at=at(5))
    first, ids, _ = await _agree(db, task)
    assert ids == ["a-started", "b-queued-earlier"], "the start time counts, not the earlier queue time"

    await _run(db, task, owner, project, run_id="c-queued-later", status="queued", queued_at=at(20))
    first, ids, summary = await _agree(db, task)
    assert ids == ["c-queued-later", "a-started", "b-queued-earlier"]
    assert summary["last_run_status"] == "queued"


@pytest.mark.asyncio
async def test_equal_times_and_runs_without_any_time_are_ordered_deterministically(db):
    task, owner, project = await _task(db)
    await _run(db, task, owner, project, run_id="run-a", status="cancelled", queued_at=at(5))
    await _run(db, task, owner, project, run_id="run-b", status="queued", queued_at=at(5))
    await _run(db, task, owner, project, run_id="run-z-untimed", status="pending", queue=False)
    await _run(db, task, owner, project, run_id="run-c-untimed", status="error", queue=False)
    first, ids, _ = await _agree(db, task)
    assert ids == ["run-b", "run-a", "run-z-untimed", "run-c-untimed"], (
        "ties fall back to the higher id; runs with no time sort after every timed run"
    )

    only_untimed, owner2, project2 = await _task(db)
    await _run(db, only_untimed, owner2, project2, run_id="u-1", status="error", queue=False)
    await _run(db, only_untimed, owner2, project2, run_id="u-2", status="cancelled", queue=False)
    first, ids, summary = await _agree(db, only_untimed)
    assert ids == ["u-2", "u-1"] and summary["last_run_status"] == "cancelled"


@pytest.mark.asyncio
async def test_reads_do_not_change_stored_runs(db):
    task, owner, project = await _task(db)
    await _run(db, task, owner, project, run_id="keep-1", status="queued", queued_at=at(3))
    await _agree(db, task)
    stored = await db.get(TaskRun, "keep-1")
    await db.refresh(stored)
    assert (stored.started_at, stored.status) == (None, "queued")


def test_the_shared_order_puts_untimed_runs_last_on_postgresql_too():
    # SQLite already sorts NULL last in DESC; PostgreSQL sorts it first unless told otherwise.
    from sqlalchemy.dialects import postgresql

    from app.services.admin.task._admin_task_stats import run_chronology_order

    statement = (
        select(TaskRun)
        .outerjoin(TaskQueueEntry, TaskQueueEntry.task_run_id == TaskRun.id)
        .order_by(*run_chronology_order())
    )
    sql = str(statement.compile(dialect=postgresql.dialect())).replace("\n", " ")
    assert (
        "ORDER BY coalesce(task_runs.started_at, task_queue_entries.queued_at) DESC NULLS LAST, task_runs.id DESC"
        in sql
    )
