"""The request's run attribution for metrics.

Metrics never read the database. The gateway resolves a request's session for its authorization anyway; the
session carries its run context (``Session.metadata["attribution"]``, kept by ``workflow_runs.octryx.attribution``
when it binds and on each phase change), and the resolution puts it here once per request. Metric hooks read
:func:`current`; missing labels mean the request belongs to no run.

A writer that holds the run itself (the independent review) carries it on the usage row instead (:func:`attach`,
read with :func:`of`): the ORM hook of ``agent_metrics`` reads the row first, then :func:`current` at the flush that
writes the row.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

_CONTEXT: ContextVar[dict[str, str] | None] = ContextVar("octryx_attribution", default=None)
_ROW_ATTRIBUTE = "_octryx_attribution"


def use(**labels: str | None) -> Token:
    """Set the request's attribution; empty values are left out."""
    return _CONTEXT.set({key: str(value) for key, value in labels.items() if value} or None)


@contextmanager
def scope(**labels: str | None) -> Iterator[None]:
    token = use(**labels)
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def current() -> dict[str, str] | None:
    return _CONTEXT.get()


def attach(row: Any, **labels: str | None) -> Any:
    """Carry the run context on the row itself (a usage row its writer adds and someone else commits)."""
    setattr(row, _ROW_ATTRIBUTE, {key: str(value) for key, value in labels.items() if value})
    return row


def of(row: Any) -> dict[str, str] | None:
    return getattr(row, _ROW_ATTRIBUTE, None) or None


__all__ = ["attach", "current", "of", "scope", "use"]
