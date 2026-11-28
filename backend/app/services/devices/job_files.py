"""Files a device job made on the person's Mac, fetched on their request (Octryx Mobile)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob, DeviceJobEvent, DeviceJobFile, UserDevice
from ...models.security.device import DEVICE_STATUS_ACTIVE
from ...time_utils import utc_now

FILE_MESSAGE_TYPES = frozenset({"file_chunk", "file_failed"})
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_OPEN = 5
MAX_SCANNED_EVENTS = 5000
SENT_TIMEOUT = timedelta(minutes=2)
KEEP = timedelta(days=1)
DEVICE_REASONS = frozenset({"unknown_job", "invalid_path", "not_found", "outside_folder", "not_shared", "secret_file",
                            "too_large", "unreadable"})
_SHA = re.compile(r"^[0-9a-f]{64}$")


class JobFileError(Exception):
    def __init__(self, reason: str, status: int = 409) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


async def reported_files(db: AsyncSession, job: DeviceJob) -> dict[str, dict[str, Any]]:
    events = (await db.execute(
        select(DeviceJobEvent.body).where(DeviceJobEvent.job_id == job.id, DeviceJobEvent.type == "job_event")
        .order_by(DeviceJobEvent.seq.desc()).limit(MAX_SCANNED_EVENTS))).scalars().all()
    found: dict[str, dict[str, Any]] = {}
    for body in events:
        if not isinstance(body, dict) or body.get("kind") != "files" or not isinstance(body.get("files"), list):
            continue
        for item in body["files"]:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                found.setdefault(item["path"], item)
    return found


async def request_file(db: AsyncSession, *, job_id: str, user_id: str, path: Any) -> DeviceJobFile:
    from .platform_switch import device_runs_platform_enabled  # noqa: PLC0415

    job = await db.get(DeviceJob, job_id) if job_id else None
    if job is None or job.owner_user_id != user_id:
        raise JobFileError("device_job_not_found", 404)
    if not isinstance(path, str) or path not in await reported_files(db, job):
        raise JobFileError("file_not_listed", 404)
    device = await db.get(UserDevice, job.device_id)
    if device is None or device.status != DEVICE_STATUS_ACTIVE or device.owner_user_id != user_id:
        raise JobFileError("device_revoked", 403)
    if device.paused:
        raise JobFileError("device_paused", 403)
    if not await device_runs_platform_enabled(db):
        raise JobFileError("device_runs_platform_disabled", 403)
    now = utc_now()
    await db.execute(delete(DeviceJobFile).where(DeviceJobFile.owner_user_id == user_id,
                                                 DeviceJobFile.created_at < now - KEEP))
    open_requests = await db.scalar(select(func.count()).select_from(DeviceJobFile).where(
        DeviceJobFile.owner_user_id == user_id, DeviceJobFile.state.in_(("pending", "sent"))))
    if int(open_requests or 0) >= MAX_OPEN:
        raise JobFileError("too_many_open", 429)
    row = DeviceJobFile(job_id=job.id, device_id=job.device_id, owner_user_id=user_id, path=path, state="pending",
                        created_at=now, updated_at=now)
    db.add(row)
    await db.flush()
    return row


async def file_for_owner(db: AsyncSession, *, job_id: str, file_id: str, user_id: str) -> DeviceJobFile:
    row = await db.get(DeviceJobFile, file_id) if file_id else None
    if row is None or row.job_id != job_id or row.owner_user_id != user_id or row.created_at < utc_now() - KEEP:
        raise JobFileError("file_not_found", 404)
    return row


async def purge_expired(db: AsyncSession) -> int:
    result = await db.execute(delete(DeviceJobFile).where(DeviceJobFile.created_at < utc_now() - KEEP))
    await db.commit()
    return int(result.rowcount or 0)


def serialize_file(row: DeviceJobFile) -> dict[str, Any]:
    return {"id": row.id, "job_id": row.job_id, "path": row.path, "name": row.path.rsplit("/", 1)[-1],
            "state": row.state, "reason": row.reason or "", "size": row.size}


async def deliver_pending(db: AsyncSession, connection: Any) -> None:
    rows = (await db.execute(select(DeviceJobFile).where(
        DeviceJobFile.device_id == connection.device_id, DeviceJobFile.state.in_(("pending", "sent"))))).scalars().all()
    now = utc_now()
    for row in rows:
        if row.state == "sent":
            if row.updated_at < now - SENT_TIMEOUT:
                row.state, row.reason, row.updated_at = "failed", "no_answer", now
            continue
        await connection.send("file_request", {"request_id": row.id, "job_id": row.job_id, "path": row.path})
        row.state, row.updated_at = "sent", now
    if rows:
        await db.flush()


class FileTransfers:
    def __init__(self) -> None:
        self._parts: dict[str, tuple[str, list[bytes], int]] = {}

    async def handle(self, db: AsyncSession, device_id: str, message_type: str, body: dict[str, Any]) -> None:
        request_id = str(body.get("request_id") or "")[:40]
        row = await db.get(DeviceJobFile, request_id) if request_id else None
        if row is None or row.device_id != device_id or row.state != "sent":
            self._parts.pop(request_id, None)
            return
        now = utc_now()
        if message_type == "file_failed":
            reason = str(body.get("reason") or "")
            row.state, row.reason, row.updated_at = "failed", reason if reason in DEVICE_REASONS else "failed", now
            self._parts.pop(request_id, None)
            await db.flush()
            return
        owner, parts, total = self._parts.get(request_id, (device_id, [], 0))
        try:
            chunk = base64.b64decode(str(body.get("data") or ""), validate=True)
        except (binascii.Error, ValueError):
            chunk = None
        if owner != device_id or chunk is None or body.get("seq") != len(parts) or total + len(chunk) > MAX_FILE_BYTES:
            self._fail(row, "transfer_invalid", now)
            await db.flush()
            return
        parts.append(chunk)
        total += len(chunk)
        if body.get("last") is not True:
            self._parts[request_id] = (owner, parts, total)
            return
        self._parts.pop(request_id, None)
        data = b"".join(parts)
        digest = hashlib.sha256(data).hexdigest()
        if body.get("size") != len(data) or not _SHA.match(str(body.get("sha256") or "")) or body["sha256"] != digest:
            self._fail(row, "transfer_invalid", now)
        else:
            row.content, row.size, row.sha256 = data, len(data), digest
            row.state, row.reason, row.updated_at = "ready", None, now
        await db.flush()

    def _fail(self, row: DeviceJobFile, reason: str, now: Any) -> None:
        self._parts.pop(row.id, None)
        row.state, row.reason, row.updated_at = "failed", reason, now


__all__ = [
    "FILE_MESSAGE_TYPES",
    "FileTransfers",
    "JobFileError",
    "deliver_pending",
    "file_for_owner",
    "purge_expired",
    "reported_files",
    "request_file",
    "serialize_file",
]
