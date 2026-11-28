"""Storing one launcher batch of transcript lines (``POST /agent-gateway/sessions/transcript``)."""

from __future__ import annotations

import asyncio
import gzip
import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob, Project, Session, SessionTranscriptChunk
from ..agent_gateway.transcript_policy_keys import transcript_policy_from_config
from ..artifact_store import artifact_store_backend, artifact_store_prefix
from ..artifact_store.service import _delete_artifact_object, _read_artifact_object, _write_artifact_object
from .redaction import note_secret_calls, redact_entry

STATE_STORED = "stored"
STATE_DUPLICATE = "duplicate"
STATE_OFF = "off"
REASON_INVALID = "transcript_batch_invalid"
STREAM_MAIN = "main"
_CLAUDE_SESSION = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_STREAM = re.compile(r"^(main|agent-[A-Za-z0-9_-]{1,70})$")
_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


class TranscriptBatchError(ValueError):
    def __init__(self, field: str) -> None:
        super().__init__(f"{REASON_INVALID}: {field}")
        self.field = field


@dataclass(frozen=True, slots=True)
class TranscriptBatch:
    claude_session_id: str
    stream: str
    first_line: int
    lines: list[Any]
    device_job_id: str = ""

    @property
    def last_line(self) -> int:
        return self.first_line + len(self.lines) - 1

    @classmethod
    def from_body(cls, body: dict[str, Any]) -> TranscriptBatch:
        claude_session_id = str(body.get("claude_session_id") or "")
        if not _CLAUDE_SESSION.match(claude_session_id):
            raise TranscriptBatchError("claude_session_id")
        stream = str(body.get("stream") or "")
        if not _STREAM.match(stream):
            raise TranscriptBatchError("stream")
        first_line = body.get("first_line")
        if type(first_line) is not int or first_line < 1:
            raise TranscriptBatchError("first_line")
        lines = body.get("lines")
        if not isinstance(lines, list) or not lines:
            raise TranscriptBatchError("lines")
        job = str(body.get("device_job_id") or "")
        return cls(claude_session_id, stream, first_line, lines, job if _JOB_ID.match(job) else "")


def object_location(backend: str, *, project_id: str, session_id: str, stream: str, first_line: int) -> str:
    relative = f"session-transcripts/{project_id}/{session_id}/{stream}/{first_line:09d}.jsonl.gz"
    prefix = artifact_store_prefix()
    return f"{prefix}/{relative}" if backend != "filesystem" and prefix else relative


def encode_lines(lines: list[Any]) -> bytes:
    return gzip.compress("\n".join(json.dumps(line, ensure_ascii=False) for line in lines).encode("utf-8"))


def decode_lines(payload: bytes) -> list[Any]:
    text = gzip.decompress(payload).decode("utf-8")
    return [json.loads(line) for line in text.split("\n") if line]


async def read_chunk_lines(chunk: SessionTranscriptChunk) -> list[Any]:
    payload = await asyncio.to_thread(_read_artifact_object, backend=chunk.storage_backend,
                                      location=chunk.storage_location)
    return decode_lines(payload)


async def delete_chunk_object(chunk: SessionTranscriptChunk) -> None:
    await asyncio.to_thread(_delete_artifact_object, backend=chunk.storage_backend, location=chunk.storage_location)


async def transcripts_enabled(db: AsyncSession, project_id: str) -> bool:
    config = (await db.execute(select(Project.config).where(Project.id == project_id))).scalar_one_or_none()
    return transcript_policy_from_config(config)[0].enabled


async def _device_job(db: AsyncSession, job_id: str, session: Session) -> str | None:
    if not job_id:
        return None
    job = await db.get(DeviceJob, job_id)
    if job is None or job.owner_user_id != session.user_id or job.workspace_id != session.project_id:
        return None
    return job.id


async def _run_id(db: AsyncSession, session: Session) -> str | None:
    from ..workflow_runs.records import active_run_for_session  # noqa: PLC0415 - heavy package

    run = await active_run_for_session(db, session.id)
    return run.id if run is not None else None


async def _previous_secret_calls(db: AsyncSession, project_id: str, batch: TranscriptBatch) -> set[str]:
    previous = (await db.execute(select(SessionTranscriptChunk).where(
        SessionTranscriptChunk.project_id == project_id,
        SessionTranscriptChunk.claude_session_id == batch.claude_session_id,
        SessionTranscriptChunk.stream == batch.stream,
        SessionTranscriptChunk.last_line < batch.first_line,
    ).order_by(SessionTranscriptChunk.last_line.desc()).limit(1))).scalar_one_or_none()
    if previous is None:
        return set()
    try:
        return note_secret_calls(await read_chunk_lines(previous), set())
    except Exception:  # noqa: BLE001 - the content rules still apply to every line
        return set()


async def store_batch(db: AsyncSession, *, session: Session, batch: TranscriptBatch) -> dict[str, Any]:
    if not await transcripts_enabled(db, session.project_id):
        return {"state": STATE_OFF}
    existing = (await db.execute(select(SessionTranscriptChunk.id).where(
        SessionTranscriptChunk.project_id == session.project_id,
        SessionTranscriptChunk.claude_session_id == batch.claude_session_id,
        SessionTranscriptChunk.stream == batch.stream,
        SessionTranscriptChunk.first_line == batch.first_line,
    ))).scalar_one_or_none()
    if existing is not None:
        return {"state": STATE_DUPLICATE, "stream": batch.stream, "last_line": batch.last_line}
    secret_ids = await _previous_secret_calls(db, session.project_id, batch)
    payload = encode_lines([redact_entry(line, secret_ids) for line in batch.lines])
    backend = artifact_store_backend()
    location = object_location(backend, project_id=session.project_id, session_id=session.id, stream=batch.stream,
                               first_line=batch.first_line)
    await asyncio.to_thread(_write_artifact_object, backend=backend, location=location, payload_bytes=payload)
    db.add(SessionTranscriptChunk(
        project_id=session.project_id, session_id=session.id, owner_user_id=session.user_id,
        claude_session_id=batch.claude_session_id, stream=batch.stream, first_line=batch.first_line,
        last_line=batch.last_line, line_count=len(batch.lines), byte_size=len(payload),
        workflow_run_id=await _run_id(db, session), device_job_id=await _device_job(db, batch.device_job_id, session),
        storage_backend=backend, storage_location=location,
    ))
    await db.flush()
    return {"state": STATE_STORED, "stream": batch.stream, "last_line": batch.last_line}


__all__ = [
    "REASON_INVALID",
    "STATE_DUPLICATE",
    "STATE_OFF",
    "STATE_STORED",
    "STREAM_MAIN",
    "TranscriptBatch",
    "TranscriptBatchError",
    "decode_lines",
    "delete_chunk_object",
    "encode_lines",
    "object_location",
    "read_chunk_lines",
    "store_batch",
    "transcripts_enabled",
]
