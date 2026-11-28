"""Rows of one Workspace: its own column (``__workspace_column__``), else the Workspace of the row an owner reference
names (``__workspace_owners__``, in order). The read filter (``services/data_access``) hides foreign private ones."""

from __future__ import annotations

from functools import partial

from sqlalchemy import case, column, func, literal, null, select
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import configure_mappers


class WorkspaceBound:
    __workspace_column__: str | None = "project_id"
    # Further Workspace columns that must be visible too (a binding between two Workspaces).
    __also_workspace_columns__: tuple[str, ...] = ()
    # {owner reference column: owner table}
    __workspace_owners__: dict[str, str] = {}
    # (kind column, the kinds that name a Workspace, id column): a row scoped to one of several kinds of things.
    __workspace_scope__: tuple[str, tuple[str, ...], str] | None = None


def workspace_bound_models() -> list[type]:
    from .core import Base

    return sorted((mapper.class_ for mapper in Base.registry.mappers if issubclass(mapper.class_, WorkspaceBound)),
                  key=lambda cls: cls.__name__)


def install_owner_attributes() -> None:
    configure_mappers()
    # The loader criteria lambda is analyzed once against the mixin itself, so it needs stand-ins there.
    WorkspaceBound.workspace_owner = column("workspace_owner")
    WorkspaceBound.workspace_grant = column("session_id")
    by_table = {cls.__table__.name: cls for cls in workspace_bound_models()}
    for cls in by_table.values():
        cls.workspace_owner = hybrid_property(_no_value, expr=partial(_owner_of, cls, by_table))
        cls.workspace_grant = _grant(cls)


def _no_value(_row: object) -> None:
    return None


def _owner_of(cls: type, by_table: dict[str, type], entity):
    # Built from the entity it is asked for (the class or an alias of it), so the criteria follow every alias. An
    # empty string never names a Workspace: a row of none stays visible like one of a shared Workspace.
    owner = owner_expression(cls, lambda attribute: getattr(entity, attribute), by_table)
    return func.coalesce(owner, literal(""))


def owner_expression(cls: type, columns, by_table: dict[str, type], seen: frozenset[str] = frozenset()):
    if cls.__tablename__ in seen:
        raise TypeError(f"{cls.__name__}: owner references run in a circle")
    parts = [columns(cls.__workspace_column__)] if cls.__workspace_column__ else []
    if cls.__workspace_scope__:
        kind, workspace_kinds, scope_id = cls.__workspace_scope__
        parts.append(case((columns(kind).in_(workspace_kinds), columns(scope_id)), else_=null()))
    for reference, owner_table in cls.__workspace_owners__.items():
        owner = by_table[owner_table]
        # An alias of its own: the owner's table can be in the outer statement too, and its rows there must not
        # stand in for the referenced one.
        alias = owner.__table__.alias()
        nested = owner_expression(owner, lambda attribute, owner=owner, alias=alias: alias.c[_column_name(
            owner, attribute)], by_table, seen | {cls.__tablename__})
        key = _referenced_key(cls.__table__.c[_column_name(cls, reference)], alias)
        parts.append(select(nested).where(key == columns(reference)).correlate_except(alias).scalar_subquery())
    if not parts:
        raise TypeError(f"{cls.__name__} names no Workspace column, scope or owner reference")
    return parts[0] if len(parts) == 1 else func.coalesce(*parts)


def _column_name(cls: type, attribute: str) -> str:
    return getattr(cls, attribute).property.columns[0].name


def _referenced_key(reference, alias):
    for key in reference.foreign_keys:
        if key.column.table.name == alias.element.name:
            return alias.c[key.column.name]
    [primary] = list(alias.primary_key)
    return primary


def _grant(cls: type):
    # The mapped attribute, never the Column: a Column set on a mapped class would be mapped a second time.
    if cls.__tablename__ == "sessions":
        return cls.__mapper__.get_property_by_column(cls.__table__.c.id).class_attribute
    session_column = cls.__table__.c.get("session_id")
    if session_column is not None and any(key.target_fullname == "sessions.id" for key in session_column.foreign_keys):
        return cls.__mapper__.get_property_by_column(session_column).class_attribute
    return null()


__all__ = ["WorkspaceBound", "install_owner_attributes", "owner_expression", "workspace_bound_models"]
