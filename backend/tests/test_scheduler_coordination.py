"""Contract: cross-process scheduler coordination, decision logic (SQLite).

- the first owner's singleton insert owns epoch 1 at once; takeover only after expiry (epoch + 1);
  renew and admission are conditional on owner, epoch and the database clock;
- reconcile registers exactly the active, schedulable rows, leaves unchanged jobs untouched and
  removes paused, deleted and unscheduled ones with their acknowledgements;
- a lost fence drops every local job and writes no acknowledgement;
- the guarded fire enqueues only for the current owner and the unchanged, active row; Redis pushes
  happen after commit and a failed push keeps the committed row;
- ``worker_application`` is applied only for the current epoch and content with a fresh next run;
- API-only TaskSchedulers never register jobs or take the lease.

SQLite has no row locks: lock ordering and fencing under concurrency are in the PostgreSQL suites.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import SchedulerJobApplication
from app.scheduler.coordination import owner_lease
from app.scheduler.coordination.application_status import scheduler_worker_applications
from app.scheduler.coordination.fingerprint import scheduler_fingerprint, task_fingerprint
from tests.scheduler_coordination_support import _expire_lease, _jobs, _scheduler, _task, coordinated  # noqa: F401

# ---- fingerprints ---------------------------------------------------------------------------------


def test_fingerprints_are_canonical_and_content_only():
    from types import SimpleNamespace as Ns

    a = scheduler_fingerprint(Ns(id="a", cron_expression="b|c", is_active=True, task_id="t"))
    b = scheduler_fingerprint(Ns(id="a|b", cron_expression="c", is_active=True, task_id="t"))
    assert a != b, "no separator ambiguity"
    assert task_fingerprint(Ns(id="x", schedule="* * * * *", is_active=None)) == task_fingerprint(
        Ns(id="x", schedule="* * * * *", is_active=False)), "only True is active"
    assert scheduler_fingerprint(Ns(id="x", cron_expression="* * * * *", is_active=True, task_id="x")) != task_fingerprint(
        Ns(id="x", schedule="* * * * *", is_active=True))


# ---- owner lease -----------------------------------------------------------------------------------


async def test_first_insert_owns_at_once_and_takeover_needs_expiry(db):
    assert await owner_lease.acquire_owner_lease(db, process_id="p1") == 1, "initial ownership immediately"
    assert await owner_lease.acquire_owner_lease(db, process_id="p2") is None
    assert await owner_lease.renew_owner_lease(db, process_id="p1", epoch=1)
    assert not await owner_lease.renew_owner_lease(db, process_id="p2", epoch=1)
    assert await owner_lease.admit_owner(db, process_id="p1", epoch=1)

    await _expire_lease(db)
    assert not await owner_lease.renew_owner_lease(db, process_id="p1", epoch=1), "expired lease is not renewed"
    assert not await owner_lease.admit_owner(db, process_id="p1", epoch=1)
    assert await owner_lease.acquire_owner_lease(db, process_id="p2") == 2
    assert not await owner_lease.admit_owner(db, process_id="p1", epoch=1), "old epoch is fenced out"
    assert await owner_lease.admit_owner(db, process_id="p2", epoch=2)

    await owner_lease.release_owner_lease(db, process_id="p1", epoch=1)
    assert await owner_lease.admit_owner(db, process_id="p2", epoch=2), "a stale release changes nothing"
    await owner_lease.release_owner_lease(db, process_id="p2", epoch=2)
    assert await owner_lease.acquire_owner_lease(db, process_id="p3") == 3


# ---- reconcile -------------------------------------------------------------------------------------


async def test_reconcile_registers_active_rows_and_leaves_unchanged_jobs_untouched(db, coordinated, monkeypatch):  # noqa: F811
    task = await _task(db, schedule="0 9 * * 0-4")
    active = await _scheduler(db, task)
    paused = await _scheduler(db, task, active=False)
    unscheduled = await _task(db, schedule=None)
    await coordinated._coordinator.tick()
    assert coordinated._coordinator.epoch == 1
    assert _jobs(coordinated) == {f"scheduler_{active.id}", f"task_{task.id}"}
    assert f"scheduler_{paused.id}" not in _jobs(coordinated) and f"task_{unscheduled.id}" not in _jobs(coordinated)
    acks = {row.job_key: row for row in (await db.execute(select(SchedulerJobApplication))).scalars()}
    assert set(acks) == {f"scheduler:{active.id}", f"task:{task.id}"}
    assert all(row.owner_epoch == 1 and row.status == "registered" and row.next_run_at for row in acks.values())
    assert acks[f"scheduler:{active.id}"].applied_fingerprint == scheduler_fingerprint(active)

    registered: list[str] = []
    original = coordinated._register_job
    monkeypatch.setattr(coordinated, "_register_job", lambda record: registered.append(record.id) or original(record))
    for _ in range(5):
        coordinated.request_reconcile()
        await coordinated._coordinator.reconcile_once()
    assert registered == [], "unchanged content is never re-registered"

    active.cron_expression = "*/10 * * * *"
    await db.commit()
    await coordinated._coordinator.reconcile_once()
    assert registered == [active.id], "only the changed row is replaced"


async def test_pause_delete_and_schedule_removal_drop_jobs_and_acknowledgements(db, coordinated):  # noqa: F811
    task = await _task(db, schedule="*/5 * * * *")
    first = await _scheduler(db, task)
    second = await _scheduler(db, task)
    await coordinated._coordinator.tick()
    assert len(_jobs(coordinated)) == 3

    first.is_active = False
    await db.delete(second)
    task.schedule = None
    await db.commit()
    await coordinated._coordinator.reconcile_once()
    assert _jobs(coordinated) == set()
    assert (await db.execute(select(func.count()).select_from(SchedulerJobApplication))).scalar_one() == 0


async def test_invalid_stored_schedule_is_acknowledged_without_a_job(db, coordinated):  # noqa: F811
    task = await _task(db)
    legacy = await _scheduler(db, task, cron="61 * * * *")
    await coordinated._coordinator.tick()
    assert _jobs(coordinated) == set()
    ack = await db.get(SchedulerJobApplication, f"scheduler:{legacy.id}")
    assert (ack.status, ack.next_run_at) == ("invalid_schedule", None)
    status = (await scheduler_worker_applications(db, [legacy]))[legacy.id]
    assert status["status"] == "invalid_schedule"


async def test_a_lost_fence_drops_local_jobs_and_writes_no_acknowledgement(db, coordinated):  # noqa: F811
    task = await _task(db)
    row = await _scheduler(db, task)
    await coordinated._coordinator.tick()
    assert _jobs(coordinated)
    await _expire_lease(db)
    assert await owner_lease.acquire_owner_lease(db, process_id="other-process") == 2
    row.cron_expression = "*/7 * * * *"
    await db.commit()
    await coordinated._coordinator.reconcile_once()
    assert coordinated._coordinator.epoch is None and _jobs(coordinated) == set()
    await db.refresh(row)
    ack = await db.get(SchedulerJobApplication, f"scheduler:{row.id}")
    await db.refresh(ack)
    assert ack.owner_epoch == 1 and ack.applied_fingerprint != scheduler_fingerprint(row), "nothing written by the old owner"
    assert (await scheduler_worker_applications(db, [row]))[row.id]["status"] == "pending"


async def test_renew_refusal_drops_jobs(db, coordinated):  # noqa: F811
    task = await _task(db)
    await _scheduler(db, task)
    coordinated._coordinator.heartbeat_seconds = 0
    await coordinated._coordinator.tick()
    assert _jobs(coordinated)
    await _expire_lease(db)
    await coordinated._coordinator.tick()
    assert coordinated._coordinator.epoch is None and _jobs(coordinated) == set()
