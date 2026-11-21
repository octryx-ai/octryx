"""Release stored secrets that a removed configuration was the last holder of.

A configuration that is deleted (a connector, for example) names candidate secrets. Every candidate
that some other holder still references stays; every candidate that nothing references any more is
destroyed together with its rotation history, in the caller's transaction (this module never
commits). The outcome carries secret ids, names and holder table names only, never values.

Holders are found in three explicit forms:

- a column with a foreign key to ``stored_secrets.id`` (read from the model metadata, so a new
  foreign key is a holder without an edit here);
- a column named ``secret_ref`` or ``*_secret_ref`` without a foreign key (``llm_providers``);
- a ``*_secret_ref`` key inside a JSON configuration column listed in ``_JSON_CONFIG_HOLDERS``.

The secret history tables are not holders: rotation-log rows (``secret_id`` NOT NULL) are removed
with the secret, access-audit rows are detached (``secret_id`` is nullable for exactly that case,
"action may be about a deleted secret").
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Column, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import Base
from ...models import (
    BuiltInToolConfig,
    ConnectorNamedConnection,
    DatabaseConnector,
    RestApiConnection,
    SecretAccessAuditLog,
    SecretRotationLog,
    StoredSecret,
)
from .service import is_secret_ref_field, normalize_secret_ref

SECRET_RELEASED = "deleted"
SECRET_KEPT_STILL_REFERENCED = "kept_still_referenced"
SECRET_NOT_FOUND = "not_found"

_SECRETS_TABLE = "stored_secrets"
_HISTORY_TABLES = frozenset({"secret_rotation_log", "secret_access_audit_log"})
# (model, JSON column attribute): configuration rows that hold ``*_secret_ref`` keys.
_JSON_CONFIG_HOLDERS: tuple[tuple[type, str], ...] = (
    (BuiltInToolConfig, "config"),
    (ConnectorNamedConnection, "config"),
    (DatabaseConnector, "connection_config"),
    (RestApiConnection, "config"),
)


@dataclass(frozen=True, slots=True)
class ExcludedHolder:
    """The configuration row being removed: its own references never keep a secret alive."""

    table: str
    row_id: str


@dataclass(slots=True)
class SecretReleaseOutcome:
    deleted: list[dict[str, Any]] = field(default_factory=list)
    kept: list[dict[str, Any]] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {"deleted": list(self.deleted), "kept": list(self.kept), "not_found": list(self.not_found)}


def config_secret_refs(config: dict[str, Any] | None) -> set[str]:
    """Secret ids named by the ``*_secret_ref`` keys of one configuration payload (nested included)."""
    found: set[str] = set()
    _collect_refs(config or {}, found)
    return found


def _collect_refs(value: Any, found: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and is_secret_ref_field(key):
                secret_id = normalize_secret_ref(item)
                if secret_id:
                    found.add(secret_id)
            else:
                _collect_refs(item, found)
    elif isinstance(value, list):
        for item in value:
            _collect_refs(item, found)


def _reference_columns() -> list[Column]:
    columns: list[Column] = []
    for table in Base.metadata.sorted_tables:
        if table.name == _SECRETS_TABLE or table.name in _HISTORY_TABLES:
            continue
        for column in table.columns:
            points_at_secrets = any(fk.column.table.name == _SECRETS_TABLE for fk in column.foreign_keys)
            named_as_ref = column.name == "secret_ref" or column.name.endswith("_secret_ref")
            if points_at_secrets or named_as_ref:
                columns.append(column)
    return columns


async def find_secret_holders(
    db: AsyncSession,
    secret_ids: Iterable[str],
    *,
    excluded: ExcludedHolder | None = None,
) -> dict[str, set[str]]:
    """Map each referenced secret id to the table names that still hold it."""
    wanted = {secret_id for secret_id in secret_ids if secret_id}
    holders: dict[str, set[str]] = {}
    if not wanted:
        return holders
    for column in _reference_columns():
        rows = await db.execute(select(column).where(column.in_(sorted(wanted))))
        for (secret_id,) in rows:
            holders.setdefault(str(secret_id), set()).add(column.table.name)
    for model, attribute in _JSON_CONFIG_HOLDERS:
        table_name = model.__tablename__
        rows = await db.execute(select(model.id, getattr(model, attribute)))
        for row_id, payload in rows:
            if excluded is not None and excluded.table == table_name and excluded.row_id == row_id:
                continue
            for secret_id in config_secret_refs(payload if isinstance(payload, dict) else {}) & wanted:
                holders.setdefault(secret_id, set()).add(table_name)
    return holders


async def release_unreferenced_secrets(
    db: AsyncSession,
    secret_ids: Iterable[str],
    *,
    excluded: ExcludedHolder | None = None,
) -> SecretReleaseOutcome:
    """Destroy every candidate secret no other holder references; keep and report the rest."""
    candidates = sorted({secret_id for secret_id in secret_ids if secret_id})
    outcome = SecretReleaseOutcome()
    if not candidates:
        return outcome
    entries = {
        entry.id: entry
        for entry in (await db.execute(select(StoredSecret).where(StoredSecret.id.in_(candidates)))).scalars()
    }
    outcome.not_found = [secret_id for secret_id in candidates if secret_id not in entries]
    holders = await find_secret_holders(db, entries, excluded=excluded)
    releasable: list[str] = []
    for secret_id in sorted(entries):
        entry = entries[secret_id]
        described = {"id": entry.id, "name": entry.name, "field_name": entry.field_name}
        if secret_id in holders:
            outcome.kept.append({**described, "state": SECRET_KEPT_STILL_REFERENCED,
                                 "held_by": sorted(holders[secret_id])})
        else:
            outcome.deleted.append({**described, "state": SECRET_RELEASED})
            releasable.append(secret_id)
    if releasable:
        # Children first: PostgreSQL enforces both foreign keys.
        await db.execute(delete(SecretRotationLog).where(SecretRotationLog.secret_id.in_(releasable)))
        await db.execute(
            update(SecretAccessAuditLog)
            .where(SecretAccessAuditLog.secret_id.in_(releasable))
            .values(secret_id=None)
        )
        for secret_id in releasable:
            await db.delete(entries[secret_id])
        await db.flush()
    return outcome
