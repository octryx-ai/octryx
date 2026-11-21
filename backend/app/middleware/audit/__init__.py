"""Audit middleware package."""

from .request_audit import audit_middleware

__all__ = ["audit_middleware"]
