"""Every ORM read of a Workspace-bound row leaves out other people's private Workspaces, except sessions shared with the
viewer. Reads it cannot reach are refused: Core reads of bound tables, text SQL outside ``reviewed_sql``."""

from __future__ import annotations

import sys
from functools import cache

from sqlalchemy import Column, Table, event, or_, select, union
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria
from sqlalchemy.sql.elements import TextClause
from sqlalchemy.sql.selectable import Select, TextualSelect
from sqlalchemy.util.concurrency import greenlet

from ...db.workspace_bound import WorkspaceBound, install_owner_attributes, workspace_bound_models
from ...time_utils import utc_now
from .reviewed_sql import TEXT_SQL_MODULES, module_path
from .viewer import PlatformMaintenance, Viewer, ViewerNotSetError, current_viewer

PRIVATE_ACCESS_MODE = "private"
_HIDDEN_CACHE = "data_access.hidden_workspaces"


class UnfilteredReadError(RuntimeError):
    def __init__(self, what: str) -> None:
        super().__init__(f"{what}: the Workspace filter cannot apply to it; read through the mapped models, or run it "
                         "under platform_maintenance(reason)")


@cache
def _bound_tables() -> dict[Table, str]:
    return {cls.__table__: cls.__table__.name for cls in workspace_bound_models()}


def _bound_tables_read(statement) -> tuple[set[str], set[str]]:
    # Bound tables the statement reads, and those it reads as plain tables, where no loader criteria can attach: a
    # Table in a FROM or a join, or a Column selected from no mapped entity of its table. A plain Column elsewhere
    # (the ORM's own get and lazy clauses) names a FROM given by the rest of the statement. A mapped element is not
    # looked into.
    bound = _bound_tables()
    read, plain, mapped, selected_columns = set(), set(), set(), set()
    pending = [(statement, False)]
    while pending:
        node, selected = pending.pop()
        entity = getattr(node, "_annotations", {}).get("parententity")
        if entity is not None:
            mapped |= {bound[table] for table in entity.mapper.tables if table in bound}
            continue
        if isinstance(node, Column):
            if (name := bound.get(node.table)) is not None:
                read.add(name)
                if selected:
                    selected_columns.add(name)
            continue
        if isinstance(node, Table):
            if (name := bound.get(node)) is not None:
                read.add(name)
                plain.add(name)
            continue
        if isinstance(node, Select):
            # Its own parts only: the FROMs a Select derives from its columns are no FROMs it names.
            pending.extend((column, True) for column in node._raw_columns)
            pending.extend((part, False) for part in _select_parts(node) if hasattr(part, "get_children"))
        else:
            pending.extend((child, selected) for child in node.get_children())
    return read | mapped, plain | (selected_columns - mapped)


def _select_parts(select_: Select) -> list:
    joins = [part for join in select_._setup_joins for part in join[:3] if part is not None]
    return [*select_._from_obj, *joins, *select_._where_criteria, *select_._having_criteria,
            *select_._order_by_clauses, *select_._group_by_clauses]


def hidden_workspace_ids(session: Session, user_id: str | None) -> tuple[str, ...]:
    return _visibility(session, user_id)[0]


async def hidden_from_viewer(db) -> tuple[str, ...]:
    viewer = current_viewer()
    if viewer is None:
        raise ViewerNotSetError(["projects"])
    if isinstance(viewer, PlatformMaintenance):
        return ()
    return await db.run_sync(lambda session: hidden_workspace_ids(session, viewer.user_id))


class HiddenWorkspaceError(RuntimeError):
    def __init__(self, workspace_id: str) -> None:
        super().__init__(f"Workspace {workspace_id} is hidden from the current viewer; nothing may be created in it "
                         "on its behalf (rows it cannot see would collide)")
        self.workspace_id = workspace_id


async def require_visible_workspace(db, workspace_id: str) -> None:
    # Before a lazy create: rows the viewer cannot see would be duplicated or overwritten.
    if workspace_id in await hidden_from_viewer(db):
        raise HiddenWorkspaceError(workspace_id)


def _visibility(session: Session, user_id: str | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    cache = session.info.setdefault(_HIDDEN_CACHE, {})
    key = user_id or ""
    if key not in cache:
        from ...models import Project  # noqa: PLC0415

        projects = Project.__table__
        connection = session.connection()
        # An empty key matches no owner, so an anonymous viewer has every private Workspace hidden.
        hidden = tuple(sorted(str(row[0]) for row in connection.execute(select(projects.c.id).where(
            projects.c.access_mode == PRIVATE_ACCESS_MODE,
            or_(projects.c.owner_user_id.is_(None), projects.c.owner_user_id != key)))))
        cache[key] = (hidden, _granted_sessions(connection, user_id) if hidden and user_id else ())
    return cache[key]


def _granted_sessions(connection, user_id: str) -> tuple[str, ...]:
    from ...models import SessionAccess, SessionCollaborator  # noqa: PLC0415

    grants, collaborators = SessionAccess.__table__, SessionCollaborator.__table__
    now = utc_now()
    rows = connection.execute(union(
        select(grants.c.session_id).where(grants.c.user_id == user_id,
                                          or_(grants.c.expires_at.is_(None), grants.c.expires_at > now)),
        select(collaborators.c.session_id).where(collaborators.c.user_id == user_id)))
    return tuple(sorted(str(row[0]) for row in rows))


def _caller_module() -> str | None:
    # An AsyncSession runs the statement in a greenlet of its own; its caller waits in the parent greenlet.
    parent = greenlet.getcurrent().parent
    for frame in (sys._getframe(2), parent.gr_frame if parent is not None else None):
        while frame is not None:
            name = frame.f_globals.get("__name__", "")
            if name.startswith("app.") and not name.startswith("app.services.data_access."):
                return name
            frame = frame.f_back
    return None


def _refuse_unreviewed_text() -> None:
    module = _caller_module()
    if module is None or module_path(module) not in TEXT_SQL_MODULES:
        raise UnfilteredReadError(f"text SQL from {module or 'outside the app'}")


def _filter_reads(state: ORMExecuteState) -> None:
    viewer = current_viewer()
    if isinstance(viewer, PlatformMaintenance):
        viewer.sessions.add(state.session)
        return
    if isinstance(state.statement, TextClause | TextualSelect):
        _refuse_unreviewed_text()
        return
    if (state.is_update or state.is_delete) and state.is_orm_statement:
        # A bulk change reaches only rows its viewer can see; the rest of the write side is PG5b's.
        if isinstance(viewer, Viewer):
            _add_criteria(state, viewer)
        return
    if not state.is_select:
        return
    tables, unmapped = _bound_tables_read(state.statement)
    if not tables:
        return
    if viewer is None:
        raise ViewerNotSetError(sorted(tables))
    if unmapped:
        raise UnfilteredReadError("a Core read of " + ", ".join(sorted(unmapped)))
    _add_criteria(state, viewer)


def _add_criteria(state: ORMExecuteState, viewer: Viewer) -> None:
    hidden, granted = _visibility(state.session, viewer.user_id)
    if not hidden:
        return
    if "workspace_owner" not in WorkspaceBound.__dict__:
        install_owner_attributes()
    if state.is_column_load:
        # A refresh or an expired attribute takes no loader criteria: a hidden row in the identity map reads as gone.
        model = state.all_mappers[0].class_ if state.all_mappers else None
        if isinstance(model, type) and issubclass(model, WorkspaceBound):
            state.statement = state.statement.where(_visible(model, hidden, granted))
        return
    if granted:
        criteria = with_loader_criteria(
            WorkspaceBound, lambda cls: cls.workspace_owner.not_in(hidden) | cls.workspace_grant.in_(granted),
            include_aliases=True, propagate_to_loaders=True)
    else:
        criteria = with_loader_criteria(WorkspaceBound, lambda cls: cls.workspace_owner.not_in(hidden),
                                        include_aliases=True, propagate_to_loaders=True)
    state.statement = state.statement.options(criteria, *_also_visible(hidden))


def _visible(model: type, hidden: tuple[str, ...], granted: tuple[str, ...]):
    visible = model.workspace_owner.not_in(hidden)
    for name in model.__also_workspace_columns__:
        column = getattr(model, name)
        visible &= column.is_(None) | column.not_in(hidden)
    return visible | model.workspace_grant.in_(granted) if granted else visible


def _also_visible(hidden: tuple[str, ...]) -> list:
    return [with_loader_criteria(model, column.is_(None) | column.not_in(hidden), include_aliases=True,
                                 propagate_to_loaders=True)
            for model in _models_with_also_columns()
            for column in (getattr(model, name) for name in model.__also_workspace_columns__)]


@cache
def _models_with_also_columns() -> tuple[type, ...]:
    return tuple(model for model in workspace_bound_models() if model.__also_workspace_columns__)


def forget_maintenance_rows(maintenance: PlatformMaintenance) -> None:
    # A later get() would answer from the identity map without asking the filter. Rows with pending changes stay
    # for their flush.
    for session in list(maintenance.sessions):
        pending = set(session.dirty) | set(session.deleted) | set(session.new)
        for row in list(session.identity_map.values()):
            # An expunge cascades to related rows, which may come later in this list.
            if isinstance(row, WorkspaceBound) and row not in pending and row in session:
                session.expunge(row)
        session.info.pop(_HIDDEN_CACHE, None)
    maintenance.sessions.clear()


def _forget_hidden_on_workspace_change(session: Session) -> None:
    from ...models import Project  # noqa: PLC0415

    if any(isinstance(row, Project) for row in (*session.new, *session.dirty, *session.deleted)):
        session.info.pop(_HIDDEN_CACHE, None)


def _forget_hidden_at_transaction_end(session: Session, transaction) -> None:
    if transaction.parent is None:
        session.info.pop(_HIDDEN_CACHE, None)


def install() -> None:
    event.listen(Session, "do_orm_execute", _filter_reads)
    event.listen(Session, "before_flush", lambda session, _context, _instances:
                 _forget_hidden_on_workspace_change(session))
    event.listen(Session, "after_transaction_end", _forget_hidden_at_transaction_end)


__all__ = [
    "HiddenWorkspaceError", "UnfilteredReadError", "forget_maintenance_rows", "hidden_from_viewer",
    "hidden_workspace_ids", "install", "require_visible_workspace",
]
