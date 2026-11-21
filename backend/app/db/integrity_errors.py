"""Explicit classification of database integrity failures.

A failing flush raises one opaque :class:`sqlalchemy.exc.IntegrityError` no
matter *which* constraint was violated. A caller that maps every
``IntegrityError`` to a single answer therefore either invents a retryable
concurrency conflict for a broken foreign key, or hides a real conflict behind an
unhandled 500. This module answers exactly one question — "did this failure
violate the unique constraint I know about?" — so a caller can keep one stable
conflict for the race it expects and an explicit, distinct state for everything
else.

Two sources, in order, and no third:

1. the driver's own structured report (``orig.diag.constraint_name``), which
   PostgreSQL provides and which names the rejected constraint exactly;
2. the single fixed grammar SQLite emits for a unique violation, because SQLite
   reports table-level unique constraints by column rather than by name.

Anything else is "not this constraint". No part of the driver's message is
returned, logged, or retained: these functions answer a boolean, and the caller
raises its own fixed detail text. Only the constraint identity the caller already
knows is ever compared.
"""

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
    """Return whether *exc* is a violation of exactly that unique constraint.

    *constraint_name* is matched against the driver's structured report where
    there is one; *table* and *columns* are the same constraint expressed the way
    SQLite reports it. Both describe one constraint, so the answer does not
    depend on the backend.
    """
    original = getattr(exc, "orig", None)
    reported_name = getattr(getattr(original, "diag", None), "constraint_name", None)
    if reported_name:
        return str(reported_name) == constraint_name
    return _sqlite_unique_columns(original) == {
        f"{table}.{column}" for column in columns
    }


def _sqlite_unique_columns(original: object) -> set[str] | None:
    """Return the qualified columns SQLite named, or ``None`` if this is not that.

    Parses a fixed grammar, not free text: everything before the first colon must
    be exactly the unique-violation phrase, and what follows is a comma-separated
    ``table.column`` list. Nothing is kept beyond the parsed identifiers.
    """
    head, separator, tail = str(original or "").partition(":")
    if not separator or head.strip().lower() != _SQLITE_UNIQUE_PREFIX:
        return None
    parsed = {part.strip() for part in tail.split(",") if part.strip()}
    return parsed or None


__all__ = ["violates_unique_constraint"]
