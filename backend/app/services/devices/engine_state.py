"""A chat thread's latest engine files (Claude Code transcripts, a Codex rollout), one encrypted object per thread,
indexed in its ``metadata_``, read back only by the device running its active job (``routes/device_session_state``)."""

from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ...models import DeviceJob, Session
from ...time_utils import utc_now
from ..agent_gateway.engine_keys import ENGINES
from ..artifact_store import artifact_store_backend, artifact_store_prefix
from ..artifact_store.service import _read_artifact_object, _write_artifact_object
from ..secret.crypto import decrypt_bytes, encrypt_bytes
from .job_state import ACTIVE_STATUSES, _audit

META_KEY = "engine_state"
MAX_STATE_BYTES = 50 * 1024 * 1024
REASON_INVALID = "session_state_invalid"
REASON_DIGEST = "session_state_digest_mismatch"
REASON_TOO_LARGE = "session_state_too_large"
REASON_UNAVAILABLE = "session_state_store_unavailable"
_ENGINE_SESSION = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def snapshot_of(thread: Session | None) -> dict[str, Any]:
    state = dict((thread.metadata_ or {}) if thread is not None else {}).get(META_KEY)
    return dict(state) if isinstance(state, dict) else {}


def _location(job: DeviceJob) -> str:
    relative = f"session-state/{job.workspace_id or 'none'}/{job.session_id}.tar.gz.fernet"
    prefix = artifact_store_prefix()
    return f"{prefix}/{relative}" if artifact_store_backend() != "filesystem" and prefix else relative


async def held_job(db: AsyncSession, device_id: str, job_id: str) -> DeviceJob | None:
    job = await db.get(DeviceJob, job_id) if job_id else None
    return job if job is not None and job.device_id == device_id and job.status in ACTIVE_STATUSES else None


async def store_snapshot(db: AsyncSession, job: DeviceJob, *, engine: str, engine_session_id: str, turn_id: str,
                         sha256: str, size: int, data: bytes) -> str:
    if engine not in ENGINES or not _ENGINE_SESSION.match(engine_session_id) or not _SHA256.match(sha256) \
            or not turn_id or turn_id != job.turn_id:
        return REASON_INVALID
    if size > MAX_STATE_BYTES or len(data) > MAX_STATE_BYTES:
        # The previous snapshot stays: a later resume continues from it.
        _audit(db, actor_id=job.owner_user_id, action="device.job.session_state_too_large", job=job,
               details={"bytes": max(size, len(data)), "engine_session_id": engine_session_id})
        await db.flush()
        return REASON_TOO_LARGE
    if not data or len(data) != size:
        return REASON_INVALID
    if hashlib.sha256(data).hexdigest() != sha256:
        return REASON_DIGEST
    thread = await db.get(Session, job.session_id)
    if thread is None:
        return REASON_INVALID
    backend, location = artifact_store_backend(), _location(job)
    sealed = await asyncio.to_thread(encrypt_bytes, data)
    try:
        await asyncio.to_thread(_write_artifact_object, backend=backend, location=location, payload_bytes=sealed)
    except Exception:  # noqa: BLE001 - a store failure keeps the previous snapshot; the next turn sends again
        return REASON_UNAVAILABLE
    thread.metadata_ = {**dict(thread.metadata_ or {}), META_KEY: {
        "engine": engine, "engine_session_id": engine_session_id, "turn_id": turn_id, "sha256": sha256,
        "bytes": size, "at": utc_now().isoformat(), "backend": backend, "location": location,
        "device_id": job.device_id}}
    flag_modified(thread, "metadata_")
    _audit(db, actor_id=job.owner_user_id, action="device.job.session_state_stored", job=job,
           details={"bytes": size, "sha256": sha256, "engine_session_id": engine_session_id})
    await db.flush()
    return ""


async def load_snapshot(db: AsyncSession, job: DeviceJob) -> tuple[bytes, str] | None:
    state = snapshot_of(await db.get(Session, job.session_id))
    if not state.get("location") or not state.get("sha256"):
        return None
    try:
        sealed = await asyncio.to_thread(_read_artifact_object, backend=str(state.get("backend") or ""),
                                         location=str(state["location"]))
        data = await asyncio.to_thread(decrypt_bytes, sealed)
    except Exception:  # noqa: BLE001 - a missing or undecryptable object reads as no snapshot
        return None
    if hashlib.sha256(data).hexdigest() != state["sha256"]:
        return None
    _audit(db, actor_id=job.owner_user_id, action="device.job.session_state_read", job=job,
           details={"sha256": state["sha256"]})
    await db.flush()
    return data, str(state["sha256"])


async def resumable_from_snapshot(db: AsyncSession, thread_id: str, engine_session_id: str) -> str:
    if not engine_session_id:
        return ""
    state = snapshot_of(await db.get(Session, thread_id))
    return engine_session_id if state.get("engine_session_id") == engine_session_id else ""


async def offer_session_state(db: AsyncSession, job: DeviceJob) -> dict[str, Any] | None:
    from .job_engine import job_engine

    resume = job.claude_session_id or (job.resume_claude_session_id or "").removeprefix("fork:")
    if not resume or str(job.profile or "").startswith("local:"):
        return None
    state = snapshot_of(await db.get(Session, job.session_id))
    if state.get("engine_session_id") != resume or state.get("engine") != await job_engine(db, job):
        return None
    return {key: state[key] for key in ("sha256", "engine", "engine_session_id")}


__all__ = [
    "MAX_STATE_BYTES",
    "META_KEY",
    "held_job",
    "load_snapshot",
    "offer_session_state",
    "resumable_from_snapshot",
    "snapshot_of",
    "store_snapshot",
]
