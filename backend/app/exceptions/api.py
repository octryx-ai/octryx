"""API-level domain exceptions."""

from __future__ import annotations

from .base import OctryxError


class ValidationError(OctryxError):
    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class ConflictError(OctryxError):
    pass


class AuthenticationError(OctryxError):
    pass


class AuthorizationError(OctryxError):
    def __init__(self, message: str, required_roles: list[str] | None = None) -> None:
        super().__init__(message)
        self.required_roles = required_roles or []
