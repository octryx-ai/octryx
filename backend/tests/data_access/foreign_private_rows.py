"""One row of every Workspace-bound model in somebody's private Workspace, built from the model's columns."""

from __future__ import annotations

import datetime as dt
import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Table,
    insert,
    select,
)
from sqlalchemy.sql.schema import Column

from app.db.workspace_bound import workspace_bound_models

MARKER = "pg5-walker-row"
# Values a model's own constraints or readers need; everything else comes from the column type.
OVERRIDES: dict[str, dict[str, object]] = {
    "control_plane_config": {"name": f"{MARKER}-control-plane"},
    "connector_named_connections": {"tool_name": "jira"},
    "plugin_installs": {"status": "active", "manifest_json": {"contributes": {"ui": {"bundle": "ui"}}}},
    "audience_receipts": {"issued_at": dt.datetime(2026, 1, 1), "expires_at": dt.datetime(2026, 1, 2)},
    "documentation_write_intents": {"operation": "create", "parent_id": "100001", "expected_version": 1},
    "knowledge_evidence_spans": {"char_start": 0, "char_end": 1, "span_ordinal": 1},
    "knowledge_span_locators": {"span_ordinal": 1},
    "mcp_server_registrations": {"owner_scope": "workspace"},
    "work_role_assignments": {"subject_kind": "user"},
    "workflow_handoffs": {"receiver_session_id": None},
}


@dataclass
class Seeded:
    workspace_id: str
    owner_id: str
    rows: dict[str, dict[str, object]] = field(default_factory=dict)

    def ids(self) -> set[str]:
        return {str(value) for row in self.rows.values() for name, value in row.items()
                if name == "id" and isinstance(value, str)}


def _typed(column: Column) -> object:
    kind = column.type
    if isinstance(kind, Enum):
        return kind.enums[0]
    if isinstance(kind, Boolean):
        return False
    if isinstance(kind, Integer):
        return 1
    if isinstance(kind, Float | Numeric):
        return 0
    if isinstance(kind, DateTime):
        return dt.datetime(2026, 1, 1)
    if isinstance(kind, Date):
        return dt.date(2026, 1, 1)
    if isinstance(kind, JSON):
        return {}
    if isinstance(kind, LargeBinary):
        return b""
    if isinstance(kind, String) and kind.length and kind.length < 36:
        return uuid.uuid4().hex[:kind.length]
    return f"{MARKER}-{uuid.uuid4().hex}"[: getattr(kind, "length", None) or 200]


_ALLOWED = re.compile(r"(\w+)\s+IN\s*\(\s*'([^']*)'")


def _checked_values(table: Table) -> dict[str, str]:
    allowed = {}
    for constraint in table.constraints:
        if isinstance(constraint, CheckConstraint):
            for name, first in _ALLOWED.findall(str(constraint.sqltext)):
                allowed.setdefault(name, first)
    return allowed


def _needs_value(column: Column) -> bool:
    return not column.nullable and column.default is None and column.server_default is None and not (
        column.primary_key and isinstance(column.type, Integer))


# Rows the private Workspace already has from its creation (the owner's membership).
CREATED_WITH_THE_WORKSPACE = frozenset({"user_projects"})


class _Factory:
    def __init__(self, db, seeded: Seeded) -> None:
        self.db, self.seeded, self.parents = db, seeded, {}

    async def row(self, table: Table, owner_column: str | None = None) -> dict[str, object]:
        if table.name in CREATED_WITH_THE_WORKSPACE:
            return {"user_id": self.seeded.owner_id, owner_column: self.seeded.workspace_id}
        values: dict[str, object] = {}
        checked = _checked_values(table)
        for column in table.columns:
            target = next(iter(column.foreign_keys), None)
            target_table = target.column.table if target is not None else None
            if column.name == owner_column or (target_table is not None and target_table.name == "projects"
                                               and not column.nullable):
                values[column.name] = self.seeded.workspace_id
            elif target_table is not None and target_table.name == "projects":
                continue
            elif target_table is not None and target_table.name == "users":
                values[column.name] = self.seeded.owner_id
            elif target_table is not None and target_table.name == "sessions" and table.name != "sessions":
                values[column.name] = (await self.parent(target_table))[target.column.name]
            elif target_table is not None and target_table is not table and (
                    not column.nullable
                    or column.name in _owner_references().get(table.name, ())):
                values[column.name] = (await self.parent(target_table))[target.column.name]
            elif column.primary_key and isinstance(column.type, String):
                values[column.name] = str(uuid.uuid4())
            elif _needs_value(column):
                values[column.name] = checked.get(column.name) or _typed(column)
        values.update(OVERRIDES.get(table.name, {}))
        if (scope := _scopes().get(table.name)) is not None:
            kind, kinds, scope_id = scope
            values.update({kind: kinds[0], scope_id: self.seeded.workspace_id})
        if owner_column:
            existing = (await self.db.execute(select(table).where(
                table.c[owner_column] == self.seeded.workspace_id).limit(1))).mappings().first()
            if existing is not None:  # created on first use of the Workspace (a capability binding)
                return dict(existing)
        result = await self.db.execute(insert(table).values(**values))
        for column, value in zip(table.primary_key.columns, result.inserted_primary_key or (), strict=False):
            values[column.name] = value
        return values

    async def parent(self, table: Table) -> dict[str, object]:
        if table.name not in self.parents:
            bound = _bound_tables()
            self.parents[table.name] = await self.row(table, bound.get(table.name))
            if table.name in bound:
                self.seeded.rows[table.name] = self.parents[table.name]
        return self.parents[table.name]


def _owner_references() -> dict[str, tuple[str, ...]]:
    # A row the walker seeds belongs to the private Workspace through each of its owner references.
    return {model.__table__.name: tuple(getattr(model, name).property.columns[0].name
                                        for name in model.__workspace_owners__)
            for model in workspace_bound_models() if model.__workspace_owners__}


def _scopes() -> dict[str, tuple[str, tuple[str, ...], str]]:
    return {model.__table__.name: model.__workspace_scope__ for model in workspace_bound_models()
            if model.__workspace_scope__}


def _bound_tables() -> dict[str, str | None]:
    return {model.__table__.name: getattr(model, model.__workspace_column__).property.columns[0].name
            if model.__workspace_column__ else None for model in workspace_bound_models()}


def _filled_targets(table: Table) -> list[Table]:
    return [key.column.table for column in table.columns for key in column.foreign_keys
            if key.column.table is not table and key.column.table.name not in ("projects", "users")
            and (not column.nullable or key.column.table.name == "sessions")]


def _touches_a_workspace(table: Table, bound: dict[str, str], seen: frozenset[str] = frozenset()) -> bool:
    if table.name in bound:
        return True
    return any(target.name not in seen and _touches_a_workspace(target, bound, seen | {table.name})
               for target in _filled_targets(table))


def _bound_table(name: str) -> Table:
    return next(model.__table__ for model in workspace_bound_models() if model.__table__.name == name)


class ForeignPrivateRows:
    # platform_parents first (rows of no Workspace that bound rows point to: part of every baseline), then
    # workspace_rows: one row per Workspace-bound model and the child rows it needs.

    def __init__(self, db, workspace_id: str, owner_id: str) -> None:
        self.seeded = Seeded(workspace_id=workspace_id, owner_id=owner_id)
        self._factory = _Factory(db, self.seeded)
        self._db = db

    async def platform_parents(self) -> None:
        bound = _bound_tables()
        pending = [target for name in sorted(bound) for target in _filled_targets(_bound_table(name))]
        while pending:
            table = pending.pop()
            if not _touches_a_workspace(table, bound):
                await self._factory.parent(table)
        await self._db.commit()

    async def workspace_rows(self) -> Seeded:
        for table_name in sorted(_bound_tables()):
            await self._factory.parent(_bound_table(table_name))
        await self._db.commit()
        return self.seeded


async def seed_foreign_private_rows(db, workspace_id: str, owner_id: str) -> Seeded:
    rows = ForeignPrivateRows(db, workspace_id, owner_id)
    await rows.platform_parents()
    return await rows.workspace_rows()


__all__ = ["MARKER", "OVERRIDES", "ForeignPrivateRows", "Seeded", "seed_foreign_private_rows"]
