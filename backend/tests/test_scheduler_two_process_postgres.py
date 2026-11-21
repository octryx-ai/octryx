"""Two actual worker processes and this test process as the API (PostgreSQL).

The probes (``tests/scheduler_coordination_probe.py``) run only registration: APScheduler paused, no
dispatcher, no recovery, no channel, no agent. Fires are commanded and only insert queue rows.

- the first worker owns the lease and applies the stored rows; the API update reaches it without a
  restart and ``worker_application`` turns ``applied`` with the worker's next run;
- right after a pause or delete commits, a fire of the previous content inserts nothing;
- a second worker stays standby; after the owner is killed (SIGKILL) and rows change, it takes over
  after expiry and applies the persisted state in its own time zone;
- with no live worker the status is ``worker_unavailable``; a clean stop releases the lease at once.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Project, Scheduler, SchedulerJobApplication, Task, TaskRun, User
from app.scheduler.coordination.application_status import scheduler_worker_applications
from app.scheduler.coordination.fingerprint import SCHEDULER_KIND, job_key, scheduler_fingerprint
from app.scheduler.coordination.owner_lease import read_lease
from app.services.admin.provider.admin_scheduler_service import (
    create_scheduler,
    delete_scheduler,
    update_scheduler,
)
from tests.alembic_model_parity_support import migrated_database, requires_postgres

pytestmark = requires_postgres
BACKEND = Path(__file__).resolve().parents[1]


class Probe:
    def __init__(self, process):
        self.process = process

    @classmethod
    async def spawn(cls, url: str, *, tz: str) -> Probe:
        env = {**os.environ, "SCHEDULER_PROBE_DATABASE_URL": url, "TZ": tz, "DEBUG": "true", "RUNTIME_PROFILE": "local"}
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "tests.scheduler_coordination_probe", "--ttl", "3", "--reconcile", "0.2",
            "--heartbeat", "0.5", cwd=str(BACKEND), env=env, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        probe = cls(process)
        assert (await probe.read())["event"] == "ready"
        return probe

    async def read(self, timeout: float = 90.0) -> dict:
        while True:
            line = await asyncio.wait_for(self.process.stdout.readline(), timeout)
            assert line, "probe exited"
            text = line.decode().strip()
            if text.startswith("PROBE "):
                return json.loads(text[6:])

    async def ask(self, payload: dict) -> dict:
        self.process.stdin.write((json.dumps(payload) + "\n").encode())
        await self.process.stdin.drain()
        return await self.read()

    def kill(self) -> None:
        self.process.send_signal(signal.SIGKILL)

    async def stop(self) -> None:
        if self.process.returncode is None:
            try:
                await self.ask({"cmd": "exit"})
            except (AssertionError, TimeoutError, BrokenPipeError, ConnectionResetError):
                pass
            await self.process.wait()


# The last state each wait saw, named in the failure: "condition not reached" alone does not show, for example,
# an unchanged next run.
_SEEN: dict[str, object] = {}


async def _until(predicate, timeout: float = 30.0, *, what: str = ""):
    _SEEN.clear()
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        value = await predicate()
        if value:
            return value
        assert asyncio.get_running_loop().time() < deadline, f"condition not reached: {what}; last seen: {_SEEN}"
        await asyncio.sleep(0.2)


async def _seed_scheduler(maker):
    async with maker() as db:
        suffix = uuid.uuid4().hex[:10]
        user = User(username=f"api-{suffix}", email=f"{suffix}@example.invalid", password_hash="not-a-login")
        project = Project(name=f"two-process-{suffix}")
        db.add_all([user, project])
        await db.flush()
        task = Task(dispatch_binding="task_definition", name="probe", task_type="agent_run", owner_id=user.id, project_id=project.id, is_active=True,
                    config={})
        db.add(task)
        await db.commit()
        created = await create_scheduler(db, user_id=user.id, payload={
            "name": "probe", "cron_expression": "*/5 * * * *", "task_id": task.id})
    return created, task.id, user.id


def _status_reader(maker, row_id):
    async def status():
        async with maker() as db:
            row = await db.get(Scheduler, row_id)
            lease = await read_lease(db)
            ack = await db.get(SchedulerJobApplication, job_key(SCHEDULER_KIND, row_id))
            _SEEN["lease"] = None if lease is None else {"epoch": lease.epoch, "live": lease.live}
            _SEEN["ack"] = None if ack is None else {
                "epoch": ack.owner_epoch, "status": ack.status, "next_run_at": str(ack.next_run_at),
                "current_content": ack.applied_fingerprint == scheduler_fingerprint(row)}
            return (await scheduler_worker_applications(db, [row]))[row_id], scheduler_fingerprint(row)

    return status


def _run_counter(maker, task_id):
    async def runs():
        async with maker() as db:
            return (await db.execute(select(func.count(TaskRun.id)).where(TaskRun.task_id == task_id))).scalar_one()

    return runs


async def _first_owner_applies_update_without_restart(maker, w1: Probe, status, row_id) -> None:
    first = await _until(lambda: _applied(status), what="the first owner applied the row")
    assert first["timezone"] == "UTC" and first["next_run_at"].endswith("Z")
    assert (await w1.ask({"cmd": "status"}))["epoch"] == 1

    # The update must change the next run at any time of day: "*/7" shares minutes 0 and 35 with "*/5", so at
    # minutes :30-:34 and :56-:59 both have the same next run and the wait below never ends.
    # "3-59/10" (minutes 3, 13, ..., 53) never shares a minute with "*/5". The wait checks the
    # content first: ``applied`` means the worker's acknowledged fingerprint is the updated row's.
    _, before_fp = await status()
    async with maker() as db:
        await update_scheduler(db, scheduler_id=row_id, payload={"cron_expression": "3-59/10 * * * *"})
    _, updated_fp = await status()
    assert updated_fp != before_fp, "the update changed the stored content"
    updated = await _until(lambda: _applied(status, fingerprint=updated_fp),
                           what="the update applied without a restart")
    assert updated["next_run_at"] != first["next_run_at"], "the update reached the worker without a restart"


async def _paused_schedule_does_not_fire(maker, w1: Probe, status, runs, row_id, task_id) -> dict:
    _, active_fp = await status()
    async with maker() as db:
        await update_scheduler(db, scheduler_id=row_id, payload={"is_active": False})
    fire = {"cmd": "fire", "kind": "scheduler", "fingerprint": active_fp, "task_id": task_id,
            "trigger_type": "scheduler", "trigger_id": row_id}
    assert (await w1.ask(fire))["fired"] is False, "a paused schedule starts no run"
    assert (await status())[0]["status"] == "paused"
    async with maker() as db:
        await update_scheduler(db, scheduler_id=row_id, payload={"is_active": True})
    assert (await w1.ask(fire))["fired"] is True, "the same content fires again once active"
    assert await runs() == 1
    return fire


async def _standby_takes_over_after_kill(url: str, maker, probes: list[Probe], w1: Probe, status, row_id) -> Probe:
    w2 = await Probe.spawn(url, tz="Asia/Tokyo")
    probes.append(w2)
    standby = await w2.ask({"cmd": "status"})
    assert standby == {"epoch": None, "jobs": []}, "a second worker stays standby"

    w1.kill()
    await w1.process.wait()
    async with maker() as db:
        await update_scheduler(db, scheduler_id=row_id, payload={"cron_expression": "*/3 * * * *"})
    taken = await _until(lambda: _owner_status(w2, job=f"scheduler_{row_id}"), what="the standby took over")
    assert taken["epoch"] == 2
    recovered = await _until(lambda: _applied(status), what="the new owner applied the row")
    assert recovered["timezone"] == "Asia/Tokyo", "the new owner applied the persisted state in its zone"
    return w2


async def _deleted_schedule_does_not_fire_and_stop_releases(
    maker, w2: Probe, status, runs, fire: dict, row_id, user_id, task_id
) -> None:
    _, current_fp = await status()
    async with maker() as db:
        await delete_scheduler(db, scheduler_id=row_id)
    gone = {**fire, "fingerprint": current_fp}
    assert (await w2.ask(gone))["fired"] is False, "a deleted schedule starts no run"
    assert await runs() == 1

    async with maker() as db:
        other = await create_scheduler(db, user_id=user_id, payload={
            "name": "after", "cron_expression": "0 2 * * *", "task_id": task_id})
    other_id = other["id"]

    async def other_status():
        async with maker() as db:
            row = await db.get(Scheduler, other_id)
            return (await scheduler_worker_applications(db, [row]))[other_id]["status"]

    await _until(lambda: _equals(other_status, "applied"), what="the second row applied")
    await w2.stop()
    assert await other_status() == "worker_unavailable", "a clean stop releases the lease at once"


async def _scenario(url: str) -> None:
    engine = create_async_engine(url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    probes: list[Probe] = []
    try:
        created, task_id, user_id = await _seed_scheduler(maker)
        row_id = created["id"]
        assert created["worker_application"]["status"] == "worker_unavailable", "no worker yet"

        status = _status_reader(maker, row_id)
        runs = _run_counter(maker, task_id)

        w1 = await Probe.spawn(url, tz="UTC")
        probes.append(w1)
        await _first_owner_applies_update_without_restart(maker, w1, status, row_id)

        fire = await _paused_schedule_does_not_fire(maker, w1, status, runs, row_id, task_id)

        w2 = await _standby_takes_over_after_kill(url, maker, probes, w1, status, row_id)

        await _deleted_schedule_does_not_fire_and_stop_releases(maker, w2, status, runs, fire, row_id, user_id, task_id)
    finally:
        for probe in probes:
            if probe.process.returncode is None:
                probe.kill()
                await probe.process.wait()
        await engine.dispose()


async def _applied(status, other_than=None, fingerprint=None):
    """The worker applied the row (``applied`` means its acknowledged fingerprint is the row's current one), with a
    next run other than ``other_than`` and, when given, the stored content ``fingerprint``."""
    value, current = await status()
    _SEEN["status"] = value
    if value["status"] == "applied" and value["next_run_at"] != other_than and fingerprint in (None, current):
        return value
    return None


async def _owner_status(probe: Probe, job: str):
    # The lease (epoch) is taken first; the jobs follow on the next reconcile, so wait for both.
    value = await probe.ask({"cmd": "status"})
    _SEEN["probe"] = value
    return value if value["epoch"] and job in value["jobs"] else None


async def _equals(read, expected):
    _SEEN["value"] = await read()
    return _SEEN["value"] == expected


def test_two_worker_processes_and_the_api(tmp_path):
    with migrated_database("postgresql", tmp_path) as database:
        asyncio.run(_scenario(database.url))
