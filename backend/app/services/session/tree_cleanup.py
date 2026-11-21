"""Hard delete of a chat session tree: the sessions, their messages and every row referencing them.

Rows with a nullable foreign key to a deleted session or message are kept and unlinked; rows with a required
foreign key are deleted. Used by thread deletion and by the live validation harness cleanup.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.schema import Table

import app.models  # noqa: F401  Ensures metadata is fully registered for the cleanup plan.

from ...db import Base
from ...models import Message, Session
from ..artifact_store import delete_tool_artifacts_for_sessions


@dataclass(frozen=True)
class CleanupOperation:
    table_name: str
    column_name: str
    mode: str
    target: str


_MANUAL_SESSION_DELETE_COLUMNS: tuple[tuple[str, str], ...] = (("session_tool_cache", "session_id"),)


def _referencing_operations(target_table_name: str) -> list[CleanupOperation]:
    operations: list[CleanupOperation] = []
    target_fullname = f"{target_table_name}.id"
    seen: set[tuple[str, str, str, str]] = set()
    for table in Base.metadata.sorted_tables:
        if table.name == target_table_name:
            continue
        if target_table_name == "sessions" and table.name == "messages":
            continue
        for column in table.columns:
            for foreign_key in column.foreign_keys:
                if foreign_key.target_fullname != target_fullname:
                    continue
                mode = "nullify" if column.nullable else "delete"
                key = (table.name, column.name, mode, target_table_name)
                if key in seen:
                    continue
                seen.add(key)
                operations.append(
                    CleanupOperation(
                        table_name=table.name,
                        column_name=column.name,
                        mode=mode,
                        target=target_table_name,
                    )
                )
    return operations


def _table_by_name(name: str) -> Table:
    table = Base.metadata.tables.get(name)
    if table is None:
        raise KeyError(f"Unknown table in session cleanup plan: {name}")
    return table


def _delete_where_ids(table: Table, column_name: str, ids: list[str]):
    return delete(table).where(table.c[column_name].in_(ids))


def _nullify_where_ids(table: Table, column_name: str, ids: list[str]):
    return update(table).where(table.c[column_name].in_(ids)).values({column_name: None})


async def collect_session_descendants(db: AsyncSession, root_session_id: str) -> list[str]:
    discovered: list[str] = []
    queue: list[str] = [root_session_id]
    seen: set[str] = set()
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        discovered.append(current)
        child_rows = await db.execute(select(Session.id).where(Session.parent_session_id == current))
        queue.extend(child_rows.scalars().all())
    return discovered


async def cleanup_session_descendants(db: AsyncSession, root_session_id: str) -> dict[str, object]:
    session_ids = await collect_session_descendants(db, root_session_id)
    if not session_ids:
        return {
            "root_session_id": root_session_id,
            "session_ids": [],
            "message_ids": [],
            "deleted": {},
            "nullified": {},
        }

    message_rows = await db.execute(select(Message.id).where(Message.session_id.in_(session_ids)))
    message_ids = message_rows.scalars().all()

    deleted: dict[str, int] = {}
    nullified: dict[str, int] = {}

    deleted_artifacts = await delete_tool_artifacts_for_sessions(db, session_ids)
    if deleted_artifacts > 0:
        deleted["tool_artifacts.session_id"] = deleted_artifacts

    await _run_operations(db, _referencing_operations("messages"), message_ids, deleted, nullified)
    await _run_operations(db, _referencing_operations("sessions"), session_ids, deleted, nullified)
    await _delete_session_rows(db, session_ids, message_ids, deleted)

    await db.commit()
    return {
        "root_session_id": root_session_id,
        "session_ids": session_ids,
        "message_ids": message_ids,
        "deleted": deleted,
        "nullified": nullified,
    }


async def run_referencing_cleanup(
    db: AsyncSession, target_table_name: str, ids: list[str], deleted: dict[str, int], nullified: dict[str, int]
) -> None:
    """Delete or nullify every row referencing ``ids`` of ``target_table_name``."""
    await _run_operations(db, _referencing_operations(target_table_name), ids, deleted, nullified)


async def _run_operations(
    db: AsyncSession,
    operations: Iterable[CleanupOperation],
    ids: list[str],
    deleted: dict[str, int],
    nullified: dict[str, int],
) -> None:
    """Delete or nullify the rows referencing ``ids``, counting affected rows per ``table.column``."""
    if not ids:
        return
    for operation in operations:
        table = _table_by_name(operation.table_name)
        statement = (
            _delete_where_ids(table, operation.column_name, ids)
            if operation.mode == "delete"
            else _nullify_where_ids(table, operation.column_name, ids)
        )
        result = await db.execute(statement)
        count = int(result.rowcount or 0)
        if count <= 0:
            continue
        key = f"{operation.table_name}.{operation.column_name}"
        bucket = deleted if operation.mode == "delete" else nullified
        bucket[key] = bucket.get(key, 0) + count


async def _delete_session_rows(
    db: AsyncSession, session_ids: list[str], message_ids: list[str], deleted: dict[str, int]
) -> None:
    """Delete the session-owned rows without a foreign key, then the messages and the sessions themselves."""
    for table_name, column_name in _MANUAL_SESSION_DELETE_COLUMNS:
        table = _table_by_name(table_name)
        result = await db.execute(_delete_where_ids(table, column_name, session_ids))
        count = int(result.rowcount or 0)
        if count > 0:
            deleted[f"{table_name}.{column_name}"] = deleted.get(f"{table_name}.{column_name}", 0) + count

    if message_ids:
        result = await db.execute(delete(Message).where(Message.id.in_(message_ids)))
        if int(result.rowcount or 0) > 0:
            deleted["messages.id"] = int(result.rowcount or 0)

    result = await db.execute(delete(Session).where(Session.id.in_(session_ids)))
    if int(result.rowcount or 0) > 0:
        deleted["sessions.id"] = int(result.rowcount or 0)
