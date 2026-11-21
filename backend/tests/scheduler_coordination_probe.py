"""A scheduling-worker probe process for the two-process scheduler tests (not a test module).

It builds only a ``TaskScheduler`` with its coordinator against the given database: APScheduler is
started *paused* (registrations get next-run times but nothing fires by the clock), the queue
dispatcher, startup recovery, channels and every other background worker are not started. Commands
arrive as JSON lines on stdin; every answer is one line ``PROBE <json>`` on stdout.

The database URL comes from ``SCHEDULER_PROBE_DATABASE_URL`` (never argv, so no credential appears
in a process listing). Commands: ``status``; ``fire`` with ``kind``, ``fingerprint``, ``task_id``, ``trigger_type``,
``trigger_id`` (calls the registered guarded callback path); ``exit`` (clean stop, releases the lease).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def emit(payload: dict) -> None:
    sys.stdout.write("PROBE " + json.dumps(payload) + "\n")
    sys.stdout.flush()


async def main(url: str, ttl: float, reconcile: float, heartbeat: float) -> None:
    from app.scheduler import TaskScheduler

    engine = create_async_engine(url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    sched = TaskScheduler(session_factory=maker)
    coordinator = sched._coordinator
    coordinator.ttl = timedelta(seconds=ttl)
    coordinator.reconcile_seconds = reconcile
    coordinator.heartbeat_seconds = heartbeat
    sched.scheduler.start(paused=True)
    await coordinator.start()
    emit({"event": "ready"})
    loop = asyncio.get_running_loop()
    try:
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            command = json.loads(line)
            if command["cmd"] == "status":
                emit({"epoch": coordinator.epoch, "jobs": sorted(job.id for job in sched.scheduler.get_jobs())})
            elif command["cmd"] == "fire":
                result = await sched._fire_scheduled(
                    command["kind"], command["fingerprint"], command["task_id"], command["trigger_type"],
                    command.get("trigger_id"),
                )
                emit({"fired": result is not None})
            elif command["cmd"] == "exit":
                break
    finally:
        await coordinator.stop()
        sched.scheduler.shutdown(wait=False)
        await engine.dispose()
        emit({"event": "stopped"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ttl", type=float, default=3.0)
    parser.add_argument("--reconcile", type=float, default=0.2)
    parser.add_argument("--heartbeat", type=float, default=0.5)
    args = parser.parse_args()
    asyncio.run(main(os.environ["SCHEDULER_PROBE_DATABASE_URL"], args.ttl, args.reconcile, args.heartbeat))
