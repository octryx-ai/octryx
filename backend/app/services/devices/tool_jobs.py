"""Device jobs without an agent: the launcher's pinned tools run on code the platform sent (one transport and one job
type for the PR review bot's scan and the check proof of From Correction to Check)."""

from __future__ import annotations

import importlib
import logging
import re
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceToolJob, DeviceToolJobArchive, UserDevice
from ...models.security.device import DEVICE_STATUS_ACTIVE
from ...time_utils import utc_now
from . import tree_archive

logger = logging.getLogger(__name__)

PENDING, SENT, DONE, TIMEOUT, FAILED = "pending", "sent", "done", "timeout", "failed"
OPEN = (PENDING, SENT)
MESSAGE_OFFER, MESSAGE_RESULT, MESSAGE_FAILED = "tool_job", "tool_job_result", "tool_job_failed"
MESSAGE_TYPES = frozenset({MESSAGE_RESULT, MESSAGE_FAILED})
MAX_ARCHIVE_BYTES = 20_000_000  # all archives of one job
MAX_STEPS = 20
MAX_TIMEOUT = 3600
TAIL = 4000  # characters of a step's stdout/stderr kept
MAX_FILE_TEXT = 5_000_000  # characters of one output file kept (an upload included)
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_TOKEN = re.compile(r"\{(archive|out):([^{}]*)\}")


class ToolJobError(ValueError):
    pass


def _step(raw: Any, archives: set[str], timeout: int) -> dict[str, Any]:
    step = dict(raw or {}) if isinstance(raw, dict) else {}
    ident, tool = str(step.get("id") or ""), str(step.get("tool") or "")
    args = step.get("args") or []
    outputs = [str(name) for name in step.get("outputs") or []]
    if not _NAME.match(ident) or not _NAME.match(tool):
        raise ToolJobError("a step needs an id and a tool id")
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise ToolJobError(f"step {ident}: args is a list of strings")
    for kind, value in (match.groups() for arg in args for match in _TOKEN.finditer(arg)):
        if (kind == "archive" and value not in archives) or (kind == "out" and value not in outputs):
            raise ToolJobError(f"step {ident}: {{{kind}:{value}}} names no archive or declared output")
    if not all(_NAME.match(name) for name in outputs):
        raise ToolJobError(f"step {ident}: an output is a plain file name")
    return {"id": ident, "tool": tool, "args": list(args), "outputs": outputs,
            "timeout": max(1, min(int(step.get("timeout") or timeout), timeout))}


async def offer(db: AsyncSession, *, purpose: str, candidates: list[str], archives: list[tree_archive.Archive],
                steps: list[dict[str, Any]], needs: list[str] | None = None, requested_by: str | None = None,
                workspace_id: str | None = None, timeout_seconds: int = 600,
                on_done: str | None = None) -> DeviceToolJob:
    timeout = max(10, min(int(timeout_seconds), MAX_TIMEOUT))
    names = [archive.name for archive in archives]
    if len(set(names)) != len(names) or not all(_NAME.match(name) for name in names):
        raise ToolJobError("archive names are distinct plain names")
    if sum(archive.bytes for archive in archives) > MAX_ARCHIVE_BYTES:
        raise ToolJobError(f"the archives are over {MAX_ARCHIVE_BYTES} bytes together")
    if not 1 <= len(steps) <= MAX_STEPS:
        raise ToolJobError(f"a job has 1 to {MAX_STEPS} steps")
    checked = [_step(step, set(names), timeout) for step in steps]
    if len({step["id"] for step in checked}) != len(checked):
        raise ToolJobError("step ids are distinct")
    if on_done is not None and ":" not in on_done:
        raise ToolJobError("on_done is 'module:function' under app.services")
    job = DeviceToolJob(purpose=purpose[:60], requested_by=requested_by, workspace_id=workspace_id,
                        candidates=[str(item) for item in candidates if item], timeout_seconds=timeout,
                        needs=sorted({str(item) for item in needs} if needs is not None else
                                     {step["tool"] for step in checked}),
                        steps=checked, on_done=on_done, state=PENDING,
                        archives=[{"name": item.name, "sha256": item.sha256, "bytes": item.bytes,
                                   "skipped": list(item.skipped)} for item in archives])
    db.add(job)
    await db.flush()
    db.add_all(DeviceToolJobArchive(job_id=job.id, name=item.name, data=item.data) for item in archives)
    await db.flush()
    return job


async def devices_of(db: AsyncSession, user_ids: list[str]) -> list[str]:
    rows = (await db.execute(select(UserDevice.id, UserDevice.owner_user_id).where(
        UserDevice.owner_user_id.in_(user_ids), UserDevice.status == DEVICE_STATUS_ACTIVE,
        UserDevice.paused.is_(False)).order_by(UserDevice.created_at))).all()
    order = {user_id: index for index, user_id in enumerate(user_ids)}
    return [device_id for device_id, owner in sorted(rows, key=lambda row: order.get(row[1], len(order)))]


def _due(job: DeviceToolJob) -> bool:
    return job.created_at + timedelta(seconds=int(job.timeout_seconds or 600)) < utc_now()


async def _finish(db: AsyncSession, job: DeviceToolJob, state: str, *, reason: str = "",
                  result: dict[str, Any] | None = None) -> bool:
    changed = (await db.execute(update(DeviceToolJob).where(DeviceToolJob.id == job.id,
                                                            DeviceToolJob.state.in_(OPEN)).values(
        state=state, reason=reason[:300] or None, result=result, finished_at=utc_now()))).rowcount
    if not changed:
        return False
    await db.execute(delete(DeviceToolJobArchive).where(DeviceToolJobArchive.job_id == job.id))
    await db.refresh(job)
    if job.on_done:
        module, _, name = job.on_done.partition(":")
        try:
            callback = getattr(importlib.import_module(f"app.services.{module}"), name)
            async with db.begin_nested():
                await callback(db, job)
        except Exception:  # noqa: BLE001 - the job's own state stays; the caller can still read result()
            logger.warning("tool_job.on_done_failed job=%s on_done=%s", job.id, job.on_done, exc_info=True)
    return True


async def expire(db: AsyncSession) -> int:
    jobs = (await db.execute(select(DeviceToolJob).where(DeviceToolJob.state.in_(OPEN)).order_by(
        DeviceToolJob.created_at).limit(50))).scalars().all()
    ended = 0
    for job in jobs:
        if _due(job):
            why = "no candidate device with the tools was connected" if job.state == PENDING else \
                "the device did not answer in time"
            ended += await _finish(db, job, TIMEOUT, reason=why)
    return ended


async def deliver(db: AsyncSession, connection: Any) -> int:
    have = {key for key, version in dict(getattr(connection, "tools", None) or {}).items() if version}
    jobs = (await db.execute(select(DeviceToolJob).where(DeviceToolJob.state == PENDING).order_by(
        DeviceToolJob.created_at).limit(50))).scalars().all()
    sent = 0
    for job in jobs:
        if connection.device_id not in (job.candidates or []) or not set(job.needs or []) <= have or _due(job):
            continue
        claimed = (await db.execute(update(DeviceToolJob).where(
            DeviceToolJob.id == job.id, DeviceToolJob.state == PENDING).values(
            state=SENT, device_id=connection.device_id, sent_at=utc_now()))).rowcount
        if not claimed:
            continue
        rows = (await db.execute(select(DeviceToolJobArchive).where(DeviceToolJobArchive.job_id == job.id))).scalars()
        meta = {item["name"]: item for item in job.archives or []}
        offered = [tree_archive.offer(tree_archive.Archive(row.name, row.data, meta[row.name]["sha256"],
                                                           len(row.data), []),
                                      device_id=connection.device_id, ttl_seconds=int(job.timeout_seconds))
                   for row in rows if row.name in meta]
        await connection.send(MESSAGE_OFFER, {"job_id": job.id, "archives": offered, "steps": job.steps,
                                              "timeout": int(job.timeout_seconds)})
        sent += 1
    await expire(db)
    return sent


def _file_text(value: Any, device_id: str) -> tuple[str, bool]:
    if isinstance(value, str):
        return value[:MAX_FILE_TEXT], len(value) > MAX_FILE_TEXT
    upload = str(dict(value or {}).get("upload") or "") if isinstance(value, dict) else ""
    data = tree_archive.read_upload(upload, device_id) if upload else None
    if data is None:
        return "", True
    return data[:MAX_FILE_TEXT].decode("utf-8", "replace"), len(data) > MAX_FILE_TEXT


def _reported(raw: Any, job: DeviceToolJob) -> list[dict[str, Any]]:
    declared = {step["id"]: step for step in job.steps or []}
    steps = []
    for item in raw if isinstance(raw, list) else []:
        item = dict(item or {}) if isinstance(item, dict) else {}
        step = declared.get(str(item.get("id") or ""))
        if step is None:
            continue
        files, cut = {}, bool(item.get("truncated"))
        for name, value in dict(item.get("files") or {}).items():
            if name in step["outputs"]:
                files[name], lost = _file_text(value, str(job.device_id))
                cut = cut or lost
        code = item.get("exit")
        steps.append({"id": step["id"], "tool": step["tool"], "status": str(item.get("status") or "error")[:20],
                      "exit": code if type(code) is int else None, "stdout": str(item.get("stdout") or "")[-TAIL:],
                      "stderr": str(item.get("stderr") or "")[-TAIL:], "files": files, "truncated": cut})
    return steps


async def apply_message(db: AsyncSession, device_id: str, message_type: str, body: dict[str, Any]) -> bool:
    job = await db.get(DeviceToolJob, str(body.get("job_id") or ""))
    if job is None or job.device_id != device_id or job.state != SENT:
        return False
    if message_type == MESSAGE_FAILED:
        return await _finish(db, job, FAILED, reason=str(body.get("reason") or "the device could not run the job"))
    return await _finish(db, job, DONE, result={"steps": _reported(body.get("steps"), job)})


async def result(db: AsyncSession, job_id: str) -> dict[str, Any] | None:
    job = await db.get(DeviceToolJob, job_id)
    if job is None:
        return {"state": FAILED, "reason": "unknown tool job", "device_id": None, "steps": []}
    if job.state in OPEN and _due(job):
        await expire(db)
        await db.refresh(job)
    if job.state in OPEN:
        return None
    return {"state": job.state, "reason": job.reason or "", "device_id": job.device_id,
            "steps": list(dict(job.result or {}).get("steps") or [])}


__all__ = ["DONE", "FAILED", "MESSAGE_OFFER", "MESSAGE_TYPES", "PENDING", "SENT", "TIMEOUT", "ToolJobError",
           "apply_message", "deliver", "devices_of", "expire", "offer", "result"]
