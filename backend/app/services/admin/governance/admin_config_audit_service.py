"""Secret-safe audit helpers for admin configuration changes."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog
from ...redaction_policy import REDACTED_SECRET, is_sensitive_key, redact_secret_payload

_REDACTED = REDACTED_SECRET
_MAX_AUDIT_STRING_LENGTH = 300


def sanitize_admin_audit_value(value: Any, *, key_hint: str = "") -> Any:
    return redact_secret_payload(value, key_hint=key_hint, max_string_length=_MAX_AUDIT_STRING_LENGTH)


def build_admin_config_audit_details(
    *,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_before = sanitize_admin_audit_value(before or {})
    safe_after = sanitize_admin_audit_value(after or {})
    changed_keys = sorted(
        key
        for key in set(safe_before) | set(safe_after)
        if safe_before.get(key) != safe_after.get(key)
    )
    details: dict[str, Any] = {
        "changed_keys": changed_keys,
        "before": safe_before,
        "after": safe_after,
    }
    if extra:
        details.update(sanitize_admin_audit_value(extra))
    return details


def record_admin_config_audit(
    db: AsyncSession,
    *,
    actor_user_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    project_id: str | None,
    details: dict[str, Any] | None = None,
) -> None:
    if not actor_user_id:
        return
    db.add(
        AuditLog(
            user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            project_id=project_id,
            details=build_admin_config_audit_details(before=before, after=after, extra=details),
        )
    )


def _is_sensitive_key(key: str) -> bool:
    return is_sensitive_key(key)
