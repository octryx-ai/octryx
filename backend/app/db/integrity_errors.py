"""Explicit classification of database integrity failures."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

#: The one SQLite form parsed here:
#: ``UNIQUE constraint failed: <table>.<column>, <table>.<column>``.
_SQLITE_UNIQUE_PREFIX = "unique constraint failed"


def violates_unique_constraint(
    exc: IntegrityError,
    *,
    constraint_name: str,
    table: str,
    columns: tuple[str, ...],
) -> bool:
    original = getattr(exc, "orig", None)
    reported_name = getattr(getattr(original, "diag", None), "constraint_name", None)
    if reported_name:
        return str(reported_name) == constraint_name
    return _sqlite_unique_columns(original) == {
        f"{table}.{column}" for column in columns
    }


def _sqlite_unique_columns(original: object) -> set[str] | None:
    head, separator, tail = str(original or "").partition(":")
    if not separator or head.strip().lower() != _SQLITE_UNIQUE_PREFIX:
        return None
    parsed = {part.strip() for part in tail.split(",") if part.strip()}
    return parsed or None


__all__ = ["violates_unique_constraint"]
