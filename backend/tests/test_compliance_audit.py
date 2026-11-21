"""Tests for Compliance Audit Export and Evidence Records."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security.compliance_audit import (
    AUDIT_CONNECTOR_ACCESS,
    AUDIT_POLICY_CHANGE,
    AUDIT_RUNTIME_ACTION,
    EVIDENCE_STATUS_DRAFT,
    EVIDENCE_STATUS_SEALED,
)
from app.services.compliance_audit.service import (
    create_audit_record,
    create_evidence_package,
    export_evidence_package,
    list_audit_records,
    list_evidence_packages,
    seal_evidence_package,
)


def _uid() -> str:
    return str(uuid.uuid4())


# ── record_audit_event ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_audit_record_basic(db: AsyncSession, auth_user):
    rec = await create_audit_record(
        db,
        event_type=AUDIT_POLICY_CHANGE,
        resource_type="budget_policy",
        resource_id=_uid(),
        resource_name="Daily limit",
        actor_user_id=str(auth_user.id),
        actor_role="admin",
        outcome="approved",
        project_id=None,
    )
    assert rec.id is not None
    assert rec.event_type == AUDIT_POLICY_CHANGE
    assert rec.outcome == "approved"


@pytest.mark.asyncio
async def test_create_audit_record_invalid_event_type_raises(db: AsyncSession):
    from app.exceptions.api import ValidationError
    with pytest.raises(ValidationError):
        await create_audit_record(db, event_type="not_a_type", resource_type="foo")


@pytest.mark.asyncio
async def test_create_audit_record_sensitive_fields_redacted(db: AsyncSession, auth_user):
    rec = await create_audit_record(
        db,
        event_type=AUDIT_CONNECTOR_ACCESS,
        resource_type="connector",
        actor_user_id=str(auth_user.id),
        details={"connector_id": "abc", "api_key": "supersecret", "result": "ok"},
        contains_sensitive=True,
    )
    assert rec.details.get("api_key") == "[REDACTED]"
    assert rec.details.get("connector_id") == "abc"
    assert "api_key" in rec.redacted_fields


@pytest.mark.asyncio
async def test_create_audit_record_no_redaction_when_not_sensitive(db: AsyncSession, auth_user):
    rec = await create_audit_record(
        db,
        event_type=AUDIT_RUNTIME_ACTION,
        resource_type="session",
        details={"action": "run", "result": "completed"},
        contains_sensitive=False,
    )
    assert rec.details.get("action") == "run"
    assert rec.details.get("result") == "completed"


# ── list_audit_records ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_audit_records_filtered_by_event_type(db: AsyncSession, auth_user):
    await create_audit_record(db, event_type=AUDIT_POLICY_CHANGE, resource_type="r1")
    await create_audit_record(db, event_type=AUDIT_CONNECTOR_ACCESS, resource_type="r2")

    results = await list_audit_records(db, event_type=AUDIT_POLICY_CHANGE)
    assert all(r.event_type == AUDIT_POLICY_CHANGE for r in results)


@pytest.mark.asyncio
async def test_list_audit_records_filtered_by_actor(db: AsyncSession, auth_user):
    await create_audit_record(db, event_type=AUDIT_RUNTIME_ACTION, resource_type="s",
                              actor_user_id=str(auth_user.id))
    await create_audit_record(db, event_type=AUDIT_RUNTIME_ACTION, resource_type="s",
                              actor_user_id="other-user")
    results = await list_audit_records(db, actor_user_id=str(auth_user.id))
    assert all(r.actor_user_id == str(auth_user.id) for r in results)


# ── evidence package lifecycle ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_evidence_package(db: AsyncSession, auth_user):
    pkg = await create_evidence_package(
        db,
        name="Q1 Compliance Review",
        created_by=str(auth_user.id),
        filter_event_types=[AUDIT_POLICY_CHANGE],
    )
    assert pkg.id is not None
    assert pkg.status == EVIDENCE_STATUS_DRAFT
    assert pkg.filter_event_types == [AUDIT_POLICY_CHANGE]


@pytest.mark.asyncio
async def test_seal_evidence_package(db: AsyncSession, auth_user):
    await create_audit_record(db, event_type=AUDIT_POLICY_CHANGE, resource_type="r")
    pkg = await create_evidence_package(
        db, name="Seal Test",
        filter_event_types=[AUDIT_POLICY_CHANGE],
    )
    sealed = await seal_evidence_package(db, pkg.id)
    assert sealed.status == EVIDENCE_STATUS_SEALED
    assert int(sealed.record_count) >= 1


@pytest.mark.asyncio
async def test_seal_already_sealed_is_idempotent(db: AsyncSession):
    pkg = await create_evidence_package(db, name="X")
    await seal_evidence_package(db, pkg.id)
    # Re-sealing should return the same sealed package
    result = await seal_evidence_package(db, pkg.id)
    assert result.status == EVIDENCE_STATUS_SEALED


@pytest.mark.asyncio
async def test_export_evidence_package(db: AsyncSession, auth_user):
    await create_audit_record(db, event_type=AUDIT_RUNTIME_ACTION, resource_type="session")
    pkg = await create_evidence_package(
        db, name="Export Test",
        filter_event_types=[AUDIT_RUNTIME_ACTION],
    )
    await seal_evidence_package(db, pkg.id)
    result = await export_evidence_package(db, pkg.id)
    assert "records" in result
    assert result["package_id"] == pkg.id


@pytest.mark.asyncio
async def test_export_draft_package_raises(db: AsyncSession):
    pkg = await create_evidence_package(db, name="Draft")
    from app.exceptions.api import ValidationError
    with pytest.raises(ValidationError, match="sealed"):
        await export_evidence_package(db, pkg.id)


@pytest.mark.asyncio
async def test_export_redacts_sensitive_records(db: AsyncSession, auth_user):
    await create_audit_record(
        db,
        event_type=AUDIT_CONNECTOR_ACCESS,
        resource_type="connector",
        details={"token": "my-secret-token", "result": "ok"},
        contains_sensitive=True,
    )
    pkg = await create_evidence_package(
        db, name="Redact Test",
        filter_event_types=[AUDIT_CONNECTOR_ACCESS],
    )
    await seal_evidence_package(db, pkg.id)
    result = await export_evidence_package(db, pkg.id)
    for rec in result["records"]:
        if rec.get("details"):
            assert rec["details"].get("token") != "my-secret-token"


@pytest.mark.asyncio
async def test_list_evidence_packages(db: AsyncSession, auth_user):
    await create_evidence_package(db, name="Pkg 1")
    await create_evidence_package(db, name="Pkg 2")
    packages = await list_evidence_packages(db)
    assert len(packages) >= 2
