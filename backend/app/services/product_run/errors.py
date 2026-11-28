"""Errors of the Product Run service."""

from __future__ import annotations


class ProductRunError(Exception):
    code = "product_run_error"
    default_message = "product run operation refused"

    def __init__(self) -> None:
        super().__init__(self.default_message)


class ProductRunScopeError(ProductRunError):
    code = "scope_mismatch"
    default_message = "product run scope does not match the session"


class InvalidProductRunInputError(ProductRunError):
    code = "invalid_input"
    default_message = "product run input is invalid"


class IllegalProductRunTransitionError(ProductRunError):
    code = "illegal_transition"
    default_message = "product run transition is not allowed"


class StaleProductRunTransitionError(ProductRunError):
    code = "stale_transition"
    default_message = "product run changed concurrently"


class ProductRunPersistenceError(ProductRunError):
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
