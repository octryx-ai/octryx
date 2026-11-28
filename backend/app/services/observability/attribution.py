"""The request's run attribution for metrics."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

_CONTEXT: ContextVar[dict[str, str] | None] = ContextVar("octryx_attribution", default=None)
_ROW_ATTRIBUTE = "_octryx_attribution"


def use(**labels: str | None) -> Token:
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
    setattr(row, _ROW_ATTRIBUTE, {key: str(value) for key, value in labels.items() if value})
    return row


def of(row: Any) -> dict[str, str] | None:
    return getattr(row, _ROW_ATTRIBUTE, None) or None


__all__ = ["attach", "current", "of", "scope", "use"]
