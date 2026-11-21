"""Errors of the Product Run service.

Every error carries a stable ``code`` and a fixed message; no identifier, state
value, or database text is ever placed into an error.
"""

from __future__ import annotations


class ProductRunError(Exception):
    """Base class; ``code`` is stable and safe to log or return."""

    code = "product_run_error"
    default_message = "product run operation refused"

    def __init__(self) -> None:
        super().__init__(self.default_message)


class ProductRunScopeError(ProductRunError):
    """The session, owner, or Workspace does not match: no run is opened."""

    code = "scope_mismatch"
    default_message = "product run scope does not match the session"


class InvalidProductRunInputError(ProductRunError):
    """An origin, actor, identifier, or gate fact is outside its closed set."""

    code = "invalid_input"
    default_message = "product run input is invalid"


class IllegalProductRunTransitionError(ProductRunError):
    """The move, its end reason, or its gate facts are not allowed by the closed tables."""

    code = "illegal_transition"
    default_message = "product run transition is not allowed"


class StaleProductRunTransitionError(ProductRunError):
    """The run or attempt changed since the handle was issued."""

    code = "stale_transition"
    default_message = "product run changed concurrently"


class ProductRunPersistenceError(ProductRunError):
    """The database refused the write; its text is never propagated."""

    code = "persistence_refused"
    default_message = "product run could not be stored"


__all__ = [
    "IllegalProductRunTransitionError",
    "InvalidProductRunInputError",
    "ProductRunError",
    "ProductRunPersistenceError",
    "ProductRunScopeError",
    "StaleProductRunTransitionError",
]
