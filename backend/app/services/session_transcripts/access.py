"""Who may see a session's full transcript, and the paged, redacted read.

Only a Workspace admin or owner (platform admins count as admins, ``access_control``) and the session's owner may
list or read a transcript; anyone else gets 404, exactly like a missing session, so a transcript's existence is not
disclosed. Every page served is an audit row (``session_transcript.read``) with who read which stream and lines.
A page is read by line number in one stream (``main`` or ``agent-<id>``) and every line passes the redaction again.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, SessionTranscriptChunk, User
from ...models.runtime.workflow_run import WorkflowRunSession
from ..access_control import get_project_role_for_user
from .redaction import note_secret_calls, redact_entry
from .store import STREAM_MAIN, read_chunk_lines

AUDIT_READ = "session_transcript.read"
DEFAULT_PAGE_LINES = 200
MAX_PAGE_LINES = 1000
ADMIN_ROLES = frozenset({"admin", "owner"})


class TranscriptAccessError(Exception):
    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Viewer:
    user: User
    workspace_admin: bool

    def may_read(self, owner_user_id: str) -> bool:
        return self.workspace_admin or owner_user_id == self.user.id


async def viewer_for(db: AsyncSession, user: User, project_id: str) -> Viewer:
    role = await get_project_role_for_user(db, user.id, project_id)
    if role is None:
        raise TranscriptAccessError(404, "workspace_not_found")
    return Viewer(user, role in ADMIN_ROLES)


def _streams(rows: list[Any]) -> list[dict[str, Any]]:
    streams: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = streams.setdefault(row.stream, {"stream": row.stream, "lines": 0, "first_line": row.first_line,
                                               "last_line": row.last_line})
        item["lines"] += row.line_count
        item["first_line"] = min(item["first_line"], row.first_line)
        item["last_line"] = max(item["last_line"], row.last_line)
    return sorted(streams.values(), key=lambda item: (item["stream"] != STREAM_MAIN, item["stream"]))


async def list_transcripts(db: AsyncSession, *, viewer: Viewer, project_id: str, session_id: str = "",
                           workflow_run_id: str = "", device_job_id: str = "") -> list[dict[str, Any]]:
    """The sessions of the Workspace with a stored transcript the viewer may read, newest first."""
    query = select(SessionTranscriptChunk).where(SessionTranscriptChunk.project_id == project_id)
    if not viewer.workspace_admin:
        query = query.where(SessionTranscriptChunk.owner_user_id == viewer.user.id)
    if session_id:
        query = query.where(SessionTranscriptChunk.session_id == session_id)
    if workflow_run_id:
        bound = select(WorkflowRunSession.session_id).where(WorkflowRunSession.run_id == workflow_run_id)
        query = query.where((SessionTranscriptChunk.workflow_run_id == workflow_run_id)
                            | SessionTranscriptChunk.session_id.in_(bound))
    if device_job_id:
        query = query.where(SessionTranscriptChunk.device_job_id == device_job_id)
    rows = (await db.execute(query)).scalars().all()
    sessions: dict[str, list[Any]] = {}
    for row in rows:
        sessions.setdefault(row.session_id, []).append(row)
    items = [{
        "session_id": session,
        "owner_user_id": chunks[0].owner_user_id,
        "claude_session_ids": sorted({chunk.claude_session_id for chunk in chunks}),
        "workflow_run_id": next((chunk.workflow_run_id for chunk in chunks if chunk.workflow_run_id), None),
        "device_job_id": next((chunk.device_job_id for chunk in chunks if chunk.device_job_id), None),
        "first_at": min(chunk.created_at for chunk in chunks).isoformat(),
        "last_at": max(chunk.created_at for chunk in chunks).isoformat(),
        "bytes_stored": sum(chunk.byte_size for chunk in chunks),
        "streams": _streams(chunks),
    } for session, chunks in sessions.items()]
    return sorted(items, key=lambda item: item["last_at"], reverse=True)


async def _session_chunks(db: AsyncSession, session_id: str) -> list[SessionTranscriptChunk]:
    return list((await db.execute(select(SessionTranscriptChunk).where(
        SessionTranscriptChunk.session_id == session_id,
    ).order_by(SessionTranscriptChunk.stream, SessionTranscriptChunk.first_line))).scalars().all())


async def read_page(db: AsyncSession, *, user: User, session_id: str, stream: str = STREAM_MAIN,
                    from_line: int = 0, limit: int = DEFAULT_PAGE_LINES) -> dict[str, Any]:
    """One page of a stream of the session's transcript, redacted; audited. 404 when absent or not readable."""
    chunks = await _session_chunks(db, session_id)
    if not chunks:
        raise TranscriptAccessError(404, "transcript_not_found")
    viewer = await viewer_for(db, user, chunks[0].project_id)
    if not viewer.may_read(chunks[0].owner_user_id):
        raise TranscriptAccessError(404, "transcript_not_found")
    limit = max(1, min(int(limit or DEFAULT_PAGE_LINES), MAX_PAGE_LINES))
    in_stream = [chunk for chunk in chunks if chunk.stream == stream]
    lines: list[dict[str, Any]] = []
    secret_ids: set[str] = set()
    for index, chunk in enumerate(in_stream):
        if chunk.last_line < from_line or len(lines) >= limit:
            continue
        if not lines and index > 0:  # a secret call just before the page: its output may open the page
            note_secret_calls(await read_chunk_lines(in_stream[index - 1]), secret_ids)
        for offset, entry in enumerate(await read_chunk_lines(chunk)):
            number = chunk.first_line + offset
            redacted = redact_entry(entry, secret_ids)  # every line in order, so the calls are seen
            if number >= from_line and len(lines) < limit:
                lines.append({"line": number, "entry": redacted})
    last_stored = max((chunk.last_line for chunk in in_stream), default=0)
    next_line = lines[-1]["line"] + 1 if lines and lines[-1]["line"] < last_stored else None
    db.add(AuditLog(user_id=user.id, session_id=session_id, action=AUDIT_READ, resource_type="session",
                    resource_id=session_id, details={
                        "project_id": chunks[0].project_id, "stream": stream, "from_line": from_line,
                        "lines": len(lines), "as": "workspace_admin" if viewer.workspace_admin else "owner"}))
    await db.commit()
    return {"session_id": session_id, "project_id": chunks[0].project_id, "owner_user_id": chunks[0].owner_user_id,
            "stream": stream, "streams": _streams(chunks), "lines": lines, "next_from_line": next_line,
            "redacted": True}


__all__ = [
    "AUDIT_READ",
    "DEFAULT_PAGE_LINES",
    "MAX_PAGE_LINES",
    "TranscriptAccessError",
    "Viewer",
    "list_transcripts",
    "read_page",
    "viewer_for",
]
