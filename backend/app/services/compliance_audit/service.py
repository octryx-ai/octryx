"""Compliance Audit Export and Evidence Records service."""

from __future__ import annotations

import uuid
from collections.abc import Collection
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.api import ValidationError
from app.exceptions.base import NotFoundError

from ...models.security.compliance_audit import (
    ALL_AUDIT_EVENT_TYPES,
    EVIDENCE_STATUS_DRAFT,
    EVIDENCE_STATUS_EXPORTED,
    EVIDENCE_STATUS_SEALED,
    ComplianceAuditRecord,
    EvidencePackage,
)
from ...time_utils import utc_now
from .projection import project_details
from .redaction import redact_details


async def create_audit_record(
    db: AsyncSession,
    *,
    event_type: str,
    resource_type: str,
    resource_id: str | None = None,
    resource_name: str | None = None,
    actor_user_id: str | None = None,
    actor_role: str | None = None,
    outcome: str | None = None,
    project_id: str | None = None,
    details: dict | None = None,
    contains_sensitive: bool = False,
    classification_level: str | None = None,
    session_id: str | None = None,
    incident_id: str | None = None,
    request_id: str | None = None,
    commit: bool = True,
) -> ComplianceAuditRecord:
    if event_type not in ALL_AUDIT_EVENT_TYPES:
        raise ValidationError(f"Invalid event_type: {event_type}")

    clean_details, redacted_fields = redact_details(details or {})

    record = ComplianceAuditRecord(
        id=str(uuid.uuid4()),
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_name=resource_name,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        outcome=outcome,
        project_id=project_id,
        details=clean_details,
        contains_sensitive=contains_sensitive or bool(redacted_fields),
        redacted_fields=redacted_fields,
        classification_level=classification_level,
        session_id=session_id,
        incident_id=incident_id,
        request_id=request_id,
    )
    db.add(record)
    if not commit:
        return record
    await db.commit()
    await db.refresh(record)
    return record


async def list_audit_records(
    db: AsyncSession,
    *,
    project_ids: Collection[str] | None = None,
    exclude_project_ids: Collection[str] = (),
    event_type: str | None = None,
    resource_type: str | None = None,
    actor_user_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    before: tuple[datetime, str] | None = None,
    limit: int = 200,
) -> list[ComplianceAuditRecord]:
    record = ComplianceAuditRecord
    stmt = select(record)
    if project_ids is not None:
        stmt = stmt.where(record.project_id.in_(list(project_ids)))
    if exclude_project_ids:
        stmt = stmt.where(or_(record.project_id.is_(None), record.project_id.notin_(list(exclude_project_ids))))
    if event_type:
        stmt = stmt.where(record.event_type == event_type)
    if resource_type:
        stmt = stmt.where(record.resource_type == resource_type)
    if actor_user_id:
        stmt = stmt.where(record.actor_user_id == actor_user_id)
    if since:
        stmt = stmt.where(record.created_at >= since)
    if until:
        stmt = stmt.where(record.created_at < until)
    if before:
        at, record_id = before
        stmt = stmt.where(or_(record.created_at < at, and_(record.created_at == at, record.id < record_id)))
    stmt = stmt.order_by(record.created_at.desc(), record.id.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def create_evidence_package(
    db: AsyncSession,
    *,
    name: str,
    created_by: str | None = None,
    project_id: str | None = None,
    description: str | None = None,
    filter_event_types: list[str] | None = None,
    filter_resource_types: list[str] | None = None,
) -> EvidencePackage:
    pkg = EvidencePackage(
        id=str(uuid.uuid4()),
        name=name,
        description=description,
        project_id=project_id,
        status=EVIDENCE_STATUS_DRAFT,
        filter_event_types=filter_event_types or [],
        filter_resource_types=filter_resource_types or [],
        created_by=created_by,
    )
    db.add(pkg)
    await db.commit()
    await db.refresh(pkg)
    return pkg


async def seal_evidence_package(
    db: AsyncSession, package_id: str
) -> EvidencePackage:
    pkg = (await db.execute(select(EvidencePackage).where(EvidencePackage.id == package_id))).scalar_one_or_none()
    if not pkg:
        raise NotFoundError("EvidencePackage", package_id)
    if pkg.status == EVIDENCE_STATUS_SEALED:
        return pkg
    # Count matching records
    stmt = select(ComplianceAuditRecord)
    if pkg.project_id:
        stmt = stmt.where(ComplianceAuditRecord.project_id == pkg.project_id)
    if pkg.filter_event_types:
        stmt = stmt.where(ComplianceAuditRecord.event_type.in_(pkg.filter_event_types))
    if pkg.filter_resource_types:
        stmt = stmt.where(ComplianceAuditRecord.resource_type.in_(pkg.filter_resource_types))
    records = (await db.execute(stmt)).scalars().all()
    redacted_count = sum(1 for r in records if r.contains_sensitive)
    pkg.status = EVIDENCE_STATUS_SEALED
    pkg.record_count = str(len(records))
    pkg.redacted_count = str(redacted_count)
    pkg.sealed_at = utc_now()
    await db.commit()
    await db.refresh(pkg)
    return pkg


async def export_evidence_package(
    db: AsyncSession, package_id: str
) -> dict[str, Any]:
    pkg = (await db.execute(select(EvidencePackage).where(EvidencePackage.id == package_id))).scalar_one_or_none()
    if not pkg:
        raise NotFoundError("EvidencePackage", package_id)
    if pkg.status not in (EVIDENCE_STATUS_SEALED, EVIDENCE_STATUS_EXPORTED):
        raise ValidationError("Package must be sealed before export")

    stmt = select(ComplianceAuditRecord)
    if pkg.project_id:
        stmt = stmt.where(ComplianceAuditRecord.project_id == pkg.project_id)
    if pkg.filter_event_types:
        stmt = stmt.where(ComplianceAuditRecord.event_type.in_(pkg.filter_event_types))
    if pkg.filter_resource_types:
        stmt = stmt.where(ComplianceAuditRecord.resource_type.in_(pkg.filter_resource_types))
    records = (await db.execute(stmt)).scalars().all()

    exported_records = []
    for r in records:
        shown, hidden = project_details(r)
        exported_records.append({
            "id": r.id,
            "event_type": r.event_type,
            "outcome": r.outcome,
            "actor_user_id": r.actor_user_id,
            "actor_role": r.actor_role,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "resource_name": r.resource_name,
            "details": shown,
            "hidden_field_count": hidden,
            "classification_level": r.classification_level,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    pkg.status = EVIDENCE_STATUS_EXPORTED
    pkg.exported_at = utc_now()
    await db.commit()

    return {
        "package_id": package_id,
        "name": pkg.name,
        "project_id": pkg.project_id,
        "record_count": len(exported_records),
        "records": exported_records,
    }


async def list_evidence_packages(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    status: str | None = None,
) -> list:
    from sqlalchemy import select
    stmt = select(EvidencePackage)
    if project_id:
        stmt = stmt.where(EvidencePackage.project_id == project_id)
    if status:
        stmt = stmt.where(EvidencePackage.status == status)
    stmt = stmt.order_by(EvidencePackage.created_at.desc())
    return list((await db.execute(stmt)).scalars().all())
