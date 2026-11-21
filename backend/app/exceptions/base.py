"""Base domain exceptions for Octryx."""

from __future__ import annotations


class OctryxError(Exception):
    """Base for all domain exceptions."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.name = self.__class__.__name__


class ExecutionRuntimeUnavailableError(OctryxError):
    """No suitable execution runtime is available for the requested operation."""


class NotFoundError(OctryxError):
    """A requested resource does not exist."""

    def __init__(self, resource: str, identifier: str | None = None) -> None:
        detail = f"{resource} not found"
        if identifier:
            detail = f"{resource} '{identifier}' not found"
        super().__init__(detail)
        self.resource = resource
        self.identifier = identifier


def to_error(exception: object) -> Exception:
    """Normalize any caught value to an Exception."""

    return exception if isinstance(exception, Exception) else Exception(str(exception))


def error_message(exception: object) -> str:
    """Extract a string message from any caught value."""

    return str(exception) if isinstance(exception, Exception) else str(exception)
