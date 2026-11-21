"""API-level domain exceptions."""

from __future__ import annotations

from .base import OctryxError


class ValidationError(OctryxError):
    """Input failed domain validation."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class ConflictError(OctryxError):
    """Operation conflicts with current resource state."""


class AuthenticationError(OctryxError):
    """Identity could not be verified."""


class AuthorizationError(OctryxError):
    """Identity verified but lacks required permission or role."""

    def __init__(self, message: str, required_roles: list[str] | None = None) -> None:
        super().__init__(message)
        self.required_roles = required_roles or []
