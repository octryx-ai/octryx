"""Alembic upgrades and downgrades in the test process skip fsync on SQLite (imported by conftest.py)."""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine

from alembic import command


def _sqlite_without_fsync(dbapi_connection, _record) -> None:
    if "sqlite" not in type(dbapi_connection).__module__:
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA synchronous=OFF")
    cursor.execute("PRAGMA journal_mode=MEMORY")
    cursor.close()


@contextmanager
def sqlite_without_fsync() -> Iterator[None]:
    event.listen(Engine, "connect", _sqlite_without_fsync)
    try:
        yield
    finally:
        event.remove(Engine, "connect", _sqlite_without_fsync)


def _without_fsync(run: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(run)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with sqlite_without_fsync():
            return run(*args, **kwargs)

    wrapper.__wrapped_for_tests__ = True
    return wrapper


for _name in ("upgrade", "downgrade"):
    if not getattr(getattr(command, _name), "__wrapped_for_tests__", False):
        setattr(command, _name, _without_fsync(getattr(command, _name)))
