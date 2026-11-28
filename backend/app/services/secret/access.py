"""The one place a stored secret is decrypted for use: each use is recorded in ``secret_access_audit_log`` (never the
value) before the value is returned, and a use that cannot be recorded is refused."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import event, insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from ...db.core import independent_write_engine
from ...models import SecretAccessAuditLog, StoredSecret
from ...time_utils import utc_now
from ..data_access.viewer import PlatformMaintenance, Viewer, current_viewer
from .crypto import decrypt_secret

READ_ACTION = "read"
# Hot paths (a provider key per model call, connector secrets per turn) record a use once per window.
AUDIT_WINDOW = timedelta(hours=1)
_MAX_REMEMBERED = 4096
_PENDING = "secret_access.pending_uses"


class SecretAccessAuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class SecretHolder:
    """A secret stored encrypted on a row of its own instead of in ``stored_secrets``."""

    entity_type: str
    entity_id: str
    workspace_id: str | None


@dataclass(frozen=True)
class _Use:
    principal: str
    actor_user_id: str | None
    secret_id: str | None
    entity_type: str | None
    entity_id: str | None
    workspace_id: str | None
    purpose: str


class _RecentUses:
    def __init__(self) -> None:
        self._until: dict[_Use, float] = {}

    def covers(self, use: _Use) -> bool:
        return self._until.get(use, 0.0) > time.monotonic()

    def remember(self, use: _Use) -> None:
        now = time.monotonic()
        if len(self._until) >= _MAX_REMEMBERED:
            self._until = {key: until for key, until in self._until.items() if until > now}
        self._until[use] = now + AUDIT_WINDOW.total_seconds()

    def clear(self) -> None:
        self._until.clear()


RECENT_USES = _RecentUses()


async def reveal_stored_secret(db: AsyncSession, entry: StoredSecret, *, purpose: str) -> str:
    value = decrypt_secret(entry.encrypted_value)
    await _record(db, _use(purpose, secret_id=entry.id, workspace_id=entry.project_id))
    return value


async def reveal_held_secret(db: AsyncSession, encrypted_value: str, *, holder: SecretHolder, purpose: str) -> str:
    value = decrypt_secret(encrypted_value)
    await _record(db, _use(purpose, entity_type=holder.entity_type, entity_id=holder.entity_id,
                           workspace_id=holder.workspace_id))
    return value


def _use(purpose: str, *, workspace_id: str | None, secret_id: str | None = None, entity_type: str | None = None,
         entity_id: str | None = None) -> _Use:
    if not purpose:
        raise ValueError("a secret is revealed only for a named purpose")
    viewer = current_viewer()
    if isinstance(viewer, Viewer) and viewer.user_id:
        principal, actor = f"user:{viewer.user_id}", viewer.user_id
    elif isinstance(viewer, PlatformMaintenance):
        principal, actor = f"platform:{viewer.caller}", None
    else:
        principal, actor = "anonymous", None
    return _Use(principal[:200], actor, secret_id, entity_type, entity_id, workspace_id, purpose[:100])


async def _record(db: AsyncSession, use: _Use) -> None:
    if RECENT_USES.covers(use) or _pending_in_transaction(db.sync_session, use):
        return
    row = _row(use)
    try:
        if await _caller_has_written(db):
            # Its own session would wait on the caller's uncommitted rows (SQLite's write lock, a Postgres foreign
            # key to a secret created in this transaction) while the caller waits on it. So the row shares the
            # caller's transaction and counts for the window only once that commits.
            connection = await db.connection()
            async with connection.begin_nested():
                await connection.execute(insert(SecretAccessAuditLog.__table__).values(**row))
            _hold_until_commit(db.sync_session, use)
            return
        await _commit_in_own_session(db, row)
    except Exception as error:
        raise SecretAccessAuditError(
            f"secret use refused: its access audit row was not written (purpose={use.purpose!r})") from error
    RECENT_USES.remember(use)


# A row written in the caller's transaction is pending per ORM transaction (the root or a savepoint): a released
# savepoint hands its uses to the enclosing transaction, a rollback discards them, and only the root's commit makes
# them count for the window.
def _pending_by_transaction(session: Session) -> dict[SessionTransaction, set[_Use]]:
    if _PENDING not in session.info:
        session.info[_PENDING] = {}
        event.listen(session, "after_commit", _settle_commit)
        event.listen(session, "after_transaction_end", _discard_ended)
    return session.info[_PENDING]


def _innermost(session: Session) -> SessionTransaction | None:
    return session.get_nested_transaction() or session.get_transaction()


def _enclosing(transaction: SessionTransaction) -> SessionTransaction | None:
    parent = transaction.parent
    while parent is not None and not parent.nested and parent.parent is not None:
        parent = parent.parent
    return parent


def _pending_in_transaction(session: Session, use: _Use) -> bool:
    pending = _pending_by_transaction(session)
    transaction = _innermost(session)
    while transaction is not None:
        if use in pending.get(transaction, ()):
            return True
        transaction = _enclosing(transaction)
    return False


def _hold_until_commit(session: Session, use: _Use) -> None:
    _pending_by_transaction(session).setdefault(_innermost(session), set()).add(use)


def _settle_commit(session: Session) -> None:
    # Dispatched before the committing transaction closes, so it is still the session's innermost one.
    transaction = _innermost(session)
    if transaction is None:
        return
    pending = _pending_by_transaction(session)
    uses = pending.pop(transaction, set())
    enclosing = _enclosing(transaction) if transaction.nested else None
    if enclosing is not None:
        pending.setdefault(enclosing, set()).update(uses)
        return
    for use in uses:
        RECENT_USES.remember(use)


def _discard_ended(session: Session, transaction: SessionTransaction) -> None:
    _pending_by_transaction(session).pop(transaction, None)


async def _caller_has_written(db: AsyncSession) -> bool:
    connection = await db.connection()
    if connection.dialect.name == "sqlite":
        raw = await connection.get_raw_connection()
        return bool(raw.driver_connection.in_transaction)
    result = await connection.exec_driver_sql("SELECT pg_current_xact_id_if_assigned()")
    return result.scalar() is not None


async def _commit_in_own_session(db: AsyncSession, row: dict[str, Any]) -> None:
    bind = db.bind
    engine = independent_write_engine(bind.engine if isinstance(bind, AsyncConnection) else bind)
    # Committed on its own: the caller's error handling can roll back its work, never this record.
    async with AsyncSession(engine) as session:
        await session.execute(insert(SecretAccessAuditLog.__table__).values(**row))
        await session.commit()


def _row(use: _Use) -> dict[str, Any]:
    task = asyncio.current_task()
    context: dict[str, Any] = {}
    viewer = current_viewer()
    if isinstance(viewer, PlatformMaintenance):
        context = {"reason": viewer.reason, "task": task.get_name() if task else None}
    return {
        "id": str(uuid.uuid4()), "secret_id": use.secret_id, "action": READ_ACTION, "entity_type": use.entity_type,
        "entity_id": use.entity_id, "actor_user_id": use.actor_user_id, "outcome": "success",
        "context_json": context, "created_at": utc_now(), "project_id": use.workspace_id,
        "principal": use.principal, "purpose": use.purpose,
    }


__all__ = [
    "AUDIT_WINDOW", "READ_ACTION", "RECENT_USES", "SecretAccessAuditError", "SecretHolder", "reveal_held_secret",
    "reveal_stored_secret",
]
