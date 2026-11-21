"""Tickets of device-sent Codex seat calls (``codex_seat_device``): admitted once, reported once.

A ticket is 32 random bytes (URL-safe), handed to the launcher's seat proxy by ``admit`` and returned with its
``report``. Only its SHA-256 is stored, as a lease in the existing ``distributed_locks`` table (no migration):

- ``lock_key`` = ``codex_seat_ticket:<sha256>``, ``owner_id`` = the platform session id,
  ``expires_at`` = admit + :data:`TICKET_SECONDS`, ``is_active`` = not yet reported;
- ``metadata_json`` = the binding: user, session, admitted model, the admitted body's canonical SHA-256, the Codex
  session id (correlation header) and the workflow run the session was bound to at admit (for the run's events).

A report claims the ticket once (``is_active`` true -> false in one conditional update): unknown, used, expired or
another session's ticket is refused and nothing is written. An answer's response id is remembered for
:data:`RESPONSE_ID_DAYS` (``codex_seat_response:<sha256>``) so a second report of the same answer is marked.

The run sweep (``workflow_runs.sweep``, every 5 minutes) turns a ticket whose report never came within its lifetime
into a ``seat_call_without_report`` event, and purges finished rows a day after they expired.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog, DistributedLock, WorkflowRun
from ....time_utils import utc_now

TICKET_PREFIX = "codex_seat_ticket:"
RESPONSE_PREFIX = "codex_seat_response:"
TICKET_SECONDS = 15 * 60
RESPONSE_ID_DAYS = 30
PURGE_AFTER = timedelta(days=1)
MAX_TICKET_CHARS = 100
EVENT_REPORT_MISMATCH = "seat_report_mismatch"
EVENT_CALL_WITHOUT_REPORT = "seat_call_without_report"
REASON_TICKET_INVALID = "seat_ticket_invalid"
REASON_TICKET_USED = "seat_ticket_used"
REASON_TICKET_EXPIRED = "seat_ticket_expired"
REASON_TICKET_FOREIGN = "seat_ticket_foreign_session"
_AUDIT_PREFIX = "model_gateway.codex_seat."


@dataclass(frozen=True, slots=True)
class TicketClaim:
    """The binding a valid, now used, ticket carried."""

    session_id: str
    user_id: str
    model: str
    body_sha256: str
    run_id: str


def body_sha256(body: Any) -> str:
    """The canonical hash of a request body (key order and spacing do not matter)."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _key(prefix: str, raw: str) -> str:
    return prefix + hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _session_run_id(db: AsyncSession, session_id: str) -> str:
    from ...workflow_runs.records import active_run_for_session

    run = await active_run_for_session(db, session_id)
    return run.id if run is not None else ""


async def issue_ticket(db: AsyncSession, *, session_id: str, user_id: str, model: str, body: Any,
                       codex_session_id: str = "") -> str:
    """A new ticket for one admitted call; the caller commits."""
    ticket = secrets.token_urlsafe(32)
    now = utc_now()
    db.add(DistributedLock(
        lock_key=_key(TICKET_PREFIX, ticket), owner_id=session_id, acquired_at=now,
        expires_at=now + timedelta(seconds=TICKET_SECONDS), is_active=True,
        metadata_json={"kind": "codex_seat_ticket", "session_id": session_id, "user_id": user_id, "model": model,
                       "body_sha256": body_sha256(body), "codex_session_id": codex_session_id[:200],
                       "run_id": await _session_run_id(db, session_id), "admitted_at": now.isoformat()},
    ))
    await db.flush()
    return ticket


async def claim_ticket(db: AsyncSession, ticket: Any, *, session_id: str, user_id: str) -> TicketClaim | str:
    """The ticket's binding, marking it used; else the fixed reason (nothing is changed then)."""
    if not isinstance(ticket, str) or not ticket or len(ticket) > MAX_TICKET_CHARS:
        return REASON_TICKET_INVALID
    key = _key(TICKET_PREFIX, ticket)
    row = (await db.execute(select(DistributedLock).where(DistributedLock.lock_key == key))).scalar_one_or_none()
    if row is None:
        return REASON_TICKET_INVALID
    meta = dict(row.metadata_json or {})
    if meta.get("session_id") != session_id or meta.get("user_id") != user_id:
        return REASON_TICKET_FOREIGN
    if not row.is_active:
        return REASON_TICKET_USED
    now = utc_now()
    if row.expires_at <= now:
        return REASON_TICKET_EXPIRED
    claimed = await db.execute(
        update(DistributedLock).where(DistributedLock.id == row.id, DistributedLock.is_active.is_(True))
        .values(is_active=False, released_at=now, metadata_json={**meta, "outcome": "reported"})
        .execution_options(synchronize_session=False))
    if claimed.rowcount != 1:
        return REASON_TICKET_USED  # a concurrent report won
    return TicketClaim(session_id=session_id, user_id=user_id, model=str(meta.get("model") or ""),
                       body_sha256=str(meta.get("body_sha256") or ""), run_id=str(meta.get("run_id") or ""))


async def seen_response(db: AsyncSession, response_id: str, *, session_id: str) -> bool:
    """Whether this response id was reported before; remembers it otherwise."""
    key = _key(RESPONSE_PREFIX, response_id)
    if (await db.execute(select(DistributedLock.id).where(DistributedLock.lock_key == key))).first() is not None:
        return True
    now = utc_now()
    db.add(DistributedLock(lock_key=key, owner_id=session_id, acquired_at=now, is_active=False, released_at=now,
                           expires_at=now + timedelta(days=RESPONSE_ID_DAYS),
                           metadata_json={"kind": "codex_seat_response"}))
    await db.flush()
    return False


async def seat_event(db: AsyncSession, *, run_id: str, session_id: str, user_id: str, kind: str,
                     detail: dict[str, Any]) -> None:
    """A run event when the call belonged to a run, else an audit record of the session (field names, no content)."""
    from ...workflow_runs.records import record_event

    run = await db.get(WorkflowRun, run_id) if run_id else None
    if run is not None:
        record_event(db, run, kind, detail={"session_id": session_id, **detail})
        return
    db.add(AuditLog(user_id=user_id, session_id=session_id, action=_AUDIT_PREFIX + kind, resource_type="session",
                    resource_id=session_id, details=detail))


async def sweep_unreported_tickets(db: AsyncSession, *, now: datetime | None = None) -> int:
    """Expired tickets without a report become ``seat_call_without_report``; finished rows are purged after a day."""
    now = now or utc_now()
    rows = (await db.execute(select(DistributedLock).where(
        DistributedLock.lock_key.like(TICKET_PREFIX + "%"), DistributedLock.is_active.is_(True),
        DistributedLock.expires_at <= now))).scalars().all()
    for row in rows:
        meta = dict(row.metadata_json or {})
        row.is_active, row.released_at = False, now
        row.metadata_json = {**meta, "outcome": "missing"}
        await seat_event(db, run_id=str(meta.get("run_id") or ""), session_id=str(meta.get("session_id") or ""),
                         user_id=str(meta.get("user_id") or ""), kind=EVENT_CALL_WITHOUT_REPORT,
                         detail={"model": str(meta.get("model") or ""), "admitted_at": meta.get("admitted_at"),
                                 "codex_session_id": meta.get("codex_session_id") or None})
    await db.execute(delete(DistributedLock).where(
        or_(DistributedLock.lock_key.like(TICKET_PREFIX + "%"), DistributedLock.lock_key.like(RESPONSE_PREFIX + "%")),
        DistributedLock.is_active.is_(False),
        DistributedLock.expires_at < now - PURGE_AFTER).execution_options(synchronize_session=False))
    await db.commit()
    return len(rows)


__all__ = [
    "EVENT_CALL_WITHOUT_REPORT",
    "EVENT_REPORT_MISMATCH",
    "REASON_TICKET_EXPIRED",
    "REASON_TICKET_FOREIGN",
    "REASON_TICKET_INVALID",
    "REASON_TICKET_USED",
    "TICKET_SECONDS",
    "TicketClaim",
    "body_sha256",
    "claim_ticket",
    "issue_ticket",
    "seat_event",
    "seen_response",
    "sweep_unreported_tickets",
]
