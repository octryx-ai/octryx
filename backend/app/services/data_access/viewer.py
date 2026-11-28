"""Who the database reads on behalf of: a person (:func:`as_viewer`, the request's private-Workspace gate) or
audited platform maintenance (:func:`platform_maintenance`). With neither, reads of Workspace-bound rows fail."""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import TypeVar
from weakref import WeakSet

AUDIT_ACTION = "platform.maintenance_read"
PLATFORM_PRINCIPAL_ID = "platform-maintenance"
T = TypeVar("T")


class RequestScope:
    # A request's viewer ends with its response: work the request leaves running reads as nobody unless it declares
    # its own viewer.
    def __init__(self) -> None:
        self.closed = False


@dataclass(frozen=True)
class Viewer:
    user_id: str | None
    scope: RequestScope | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class PlatformMaintenance:
    reason: str
    caller: str
    # The database sessions that read under it; they forget its rows when it ends (read_filter).
    sessions: WeakSet = field(default_factory=WeakSet, compare=False, repr=False)


DataViewer = Viewer | PlatformMaintenance
_DATA_VIEWER: ContextVar[DataViewer | None] = ContextVar("data_viewer", default=None)
_REQUEST_SCOPE: ContextVar[RequestScope | None] = ContextVar("data_viewer_request_scope", default=None)


class ViewerNotSetError(RuntimeError):
    def __init__(self, tables: list[str]) -> None:
        super().__init__(
            "Workspace-bound read without a data viewer (tables: " + ", ".join(sorted(tables)) + "); "
            "run it under as_viewer(user_id) or platform_maintenance(reason)")


def current_viewer() -> DataViewer | None:
    viewer = _DATA_VIEWER.get()
    if isinstance(viewer, Viewer) and viewer.scope is not None and viewer.scope.closed:
        return None
    return viewer


def set_viewer(viewer: DataViewer | None) -> Token:
    return _DATA_VIEWER.set(viewer)


def reset_viewer(token: Token) -> None:
    _DATA_VIEWER.reset(token)


def bind_request_viewer(user_id: str | None) -> Viewer:
    viewer = Viewer(str(user_id) if user_id else None, scope=_REQUEST_SCOPE.get())
    _DATA_VIEWER.set(viewer)
    return viewer


@contextmanager
def request_scope() -> Iterator[RequestScope]:
    scope = RequestScope()
    scope_token, viewer_token = _REQUEST_SCOPE.set(scope), _DATA_VIEWER.set(None)
    try:
        yield scope
    finally:
        scope.closed = True
        _DATA_VIEWER.reset(viewer_token)
        _REQUEST_SCOPE.reset(scope_token)


@contextmanager
def as_viewer(user_id: str | None) -> Iterator[Viewer]:
    """Reads as ``user_id`` (``None``: anonymous, every private Workspace hidden) until the block ends."""
    viewer = Viewer(str(user_id) if user_id else None)
    token = _DATA_VIEWER.set(viewer)
    try:
        yield viewer
    finally:
        _DATA_VIEWER.reset(token)


def background_viewer() -> DataViewer | None:
    """The current viewer for work that outlives the request: the same person, without the request's lifetime."""
    viewer = current_viewer()
    return Viewer(viewer.user_id) if isinstance(viewer, Viewer) else viewer


@contextmanager
def reading_as(viewer: DataViewer | None) -> Iterator[None]:
    token = _DATA_VIEWER.set(viewer)
    try:
        yield
    finally:
        _DATA_VIEWER.reset(token)


async def run_as(viewer: DataViewer | None, work: Awaitable[T]) -> T:
    """``work`` that outlives the request reads as ``viewer`` (:func:`background_viewer`, or a person's
    :class:`Viewer`), never as the request's own viewer, which ends with the response."""
    with reading_as(viewer):
        return await work


def _caller(depth: int) -> str:
    frame = sys._getframe(depth)
    return f"{frame.f_globals.get('__name__', '?')}.{frame.f_code.co_name}"


class PlatformMaintenanceAuditError(RuntimeError):
    pass


class platform_maintenance:  # noqa: N801 - used like the context manager functions next to it
    """Reads every Workspace, private ones included. Pinned call sites only (``tests/guards``); entered only once
    its audit row is committed."""

    def __init__(self, reason: str) -> None:
        self.state = PlatformMaintenance(reason=reason, caller=_caller(2))
        self._token: Token | None = None

    async def __aenter__(self) -> PlatformMaintenance:
        actor = current_viewer()
        try:
            await _audit(self.state, actor.user_id if isinstance(actor, Viewer) else None)
        except Exception as error:
            raise PlatformMaintenanceAuditError(
                f"platform maintenance refused: its audit row was not written (reason={self.state.reason!r})"
            ) from error
        self._token = _DATA_VIEWER.set(self.state)
        return self.state

    async def __aexit__(self, *_exc) -> None:
        from .read_filter import forget_maintenance_rows  # noqa: PLC0415 - read_filter imports this module

        _DATA_VIEWER.reset(self._token)
        forget_maintenance_rows(self.state)


async def _audit(state: PlatformMaintenance, actor_user_id: str | None) -> None:
    from ...db import core as db_core  # noqa: PLC0415
    from ...models import AuditLog, User  # noqa: PLC0415

    user_id = actor_user_id or PLATFORM_PRINCIPAL_ID
    # A session of its own, committed before the bypass starts: a rollback of the caller's work keeps the record.
    async with db_core.async_session_factory() as db:
        if actor_user_id is None and await db.get(User, PLATFORM_PRINCIPAL_ID) is None:
            db.add(User(id=PLATFORM_PRINCIPAL_ID, username=PLATFORM_PRINCIPAL_ID,
                        email=f"{PLATFORM_PRINCIPAL_ID}@octryx.local", password_hash="disabled-system-principal",
                        auth_source="system", account_type="system", display_name="Platform maintenance",
                        is_active=False))
        db.add(AuditLog(user_id=user_id, action=AUDIT_ACTION, resource_type="data_access",
                        resource_id=state.reason[:200], details={"reason": state.reason, "caller": state.caller}))
        await db.commit()


__all__ = [
    "AUDIT_ACTION", "PLATFORM_PRINCIPAL_ID", "DataViewer", "PlatformMaintenance", "PlatformMaintenanceAuditError",
    "RequestScope", "Viewer",
    "ViewerNotSetError", "as_viewer", "background_viewer", "bind_request_viewer", "current_viewer",
    "platform_maintenance", "reading_as", "request_scope", "reset_viewer", "run_as", "set_viewer",
]
