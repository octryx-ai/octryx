"""Shared helpers for the test_admin_provider_service_contract_* modules."""

from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog


async def _audit_log(db, action: str, resource_id: str) -> AuditLog:
    return (
        await db.execute(
            select(AuditLog).where(
                AuditLog.action == action,
                AuditLog.resource_id == resource_id,
            )
        )
    ).scalar_one()


def _assert_provider_audit_has_no_secret_values(details: dict) -> None:
    details_text = str(details)
    assert "sk-panel" not in details_text
    assert "sk-config-audit" not in details_text
    assert "secret-id" not in details_text
    assert "aws-secret" not in details_text
    assert "oauth-secret" not in details_text
