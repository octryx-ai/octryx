"""Base domain exceptions for Octryx."""

from __future__ import annotations


class OctryxError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.name = self.__class__.__name__


class ExecutionRuntimeUnavailableError(OctryxError):
    pass


class NotFoundError(OctryxError):
    def __init__(self, resource: str, identifier: str | None = None) -> None:
        detail = f"{resource} not found"
        if identifier:
            detail = f"{resource} '{identifier}' not found"
        super().__init__(detail)
        self.resource = resource
        self.identifier = identifier


def error_message(exception: object) -> str:
    return str(exception) if isinstance(exception, Exception) else str(exception)
