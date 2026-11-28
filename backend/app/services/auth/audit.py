"""Secret-safe audit helpers for authentication and identity administration."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog
from ...trusted_proxy_policy import effective_client_address
from ..redaction_policy import redact_secret_payload

MAX_AUTH_AUDIT_STRING_LENGTH = 300


def sanitize_auth_audit_details(details: dict[str, Any] | None) -> dict[str, Any]:
    return redact_secret_payload(
        details or {},
        max_string_length=MAX_AUTH_AUDIT_STRING_LENGTH,
    )


def client_ip_from_request(request: Request | None) -> str | None:
    return effective_client_address(request)


def record_auth_audit_event(
    db: AsyncSession,
    *,
    user_id: str | None,
    action: str,
    resource_type: str = "auth",
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    if not user_id:
        return
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id or user_id,
            details=sanitize_auth_audit_details(details),
            ip_address=client_ip_from_request(request),
        )
    )


__all__ = [
    "client_ip_from_request",
    "record_auth_audit_event",
    "sanitize_auth_audit_details",
]
