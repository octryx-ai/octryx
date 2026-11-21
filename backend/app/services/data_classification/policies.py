"""The default platform policies and the policy lookup."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.security.data_classification import (
    CLASSIFICATION_CONFIDENTIAL,
    CLASSIFICATION_INTERNAL,
    CLASSIFICATION_RESTRICTED,
    ENTITY_AGENT_OUTPUT,
    ENTITY_CONNECTOR_PAYLOAD,
    ENTITY_DOCUMENT,
    ENTITY_EVALUATION,
    ENTITY_HCM_DATA,
    ENTITY_KNOWLEDGE_MAP,
    ENTITY_LEGAL_DATA,
    ENTITY_MESSAGE,
    ENTITY_PM_DATA,
    ENTITY_SESSION,
    ENTITY_TRACE_SPAN,
    ENTITY_TURN_TRACE,
    EXPORT_ACTION_ALLOW,
    EXPORT_ACTION_DENY,
    EXPORT_ACTION_REDACT,
    DataClassificationPolicy,
)

# ---------------------------------------------------------------------------
# Default platform policies
# ---------------------------------------------------------------------------

_DEFAULT_POLICIES: list[dict[str, Any]] = [
    {
        "entity_type": ENTITY_SESSION,
        "default_classification": CLASSIFICATION_INTERNAL,
        "retention_days": 365,
        "export_action": EXPORT_ACTION_REDACT,
        "auto_redact_pii": True,
        "require_export_audit": True,
    },
    {
        "entity_type": ENTITY_MESSAGE,
        "default_classification": CLASSIFICATION_INTERNAL,
        "retention_days": 365,
        "export_action": EXPORT_ACTION_REDACT,
        "auto_redact_pii": True,
        "require_export_audit": True,
    },
    {
        "entity_type": ENTITY_TRACE_SPAN,
        "default_classification": CLASSIFICATION_CONFIDENTIAL,
        "retention_days": 90,
        "export_action": EXPORT_ACTION_REDACT,
        "auto_redact_pii": True,
        "require_export_audit": True,
    },
    {
        "entity_type": ENTITY_TURN_TRACE,
        "default_classification": CLASSIFICATION_CONFIDENTIAL,
        "retention_days": 90,
        "export_action": EXPORT_ACTION_REDACT,
        "auto_redact_pii": True,
        "require_export_audit": True,
    },
    {
        "entity_type": ENTITY_KNOWLEDGE_MAP,
        "default_classification": CLASSIFICATION_INTERNAL,
        "retention_days": None,  # Keep indefinitely
        "export_action": EXPORT_ACTION_ALLOW,
        "auto_redact_pii": False,
        "require_export_audit": False,
    },
    {
        "entity_type": ENTITY_EVALUATION,
        "default_classification": CLASSIFICATION_INTERNAL,
        "retention_days": 730,
        "export_action": EXPORT_ACTION_ALLOW,
        "auto_redact_pii": False,
        "require_export_audit": False,
    },
    {
        "entity_type": ENTITY_DOCUMENT,
        "default_classification": CLASSIFICATION_CONFIDENTIAL,
        "retention_days": 1825,  # 5 years
        "export_action": EXPORT_ACTION_REDACT,
        "auto_redact_pii": True,
        "require_export_audit": True,
    },
    {
        "entity_type": ENTITY_CONNECTOR_PAYLOAD,
        "default_classification": CLASSIFICATION_CONFIDENTIAL,
        "retention_days": 30,
        "export_action": EXPORT_ACTION_DENY,
        "auto_redact_pii": True,
        "require_export_audit": True,
    },
    {
        "entity_type": ENTITY_AGENT_OUTPUT,
        "default_classification": CLASSIFICATION_INTERNAL,
        "retention_days": 180,
        "export_action": EXPORT_ACTION_REDACT,
        "auto_redact_pii": True,
        "require_export_audit": True,
    },
    {
        "entity_type": ENTITY_HCM_DATA,
        "default_classification": CLASSIFICATION_RESTRICTED,
        "retention_days": 3650,  # 10 years
        "export_action": EXPORT_ACTION_DENY,
        "auto_redact_pii": True,
        "require_export_audit": True,
    },
    {
        "entity_type": ENTITY_LEGAL_DATA,
        "default_classification": CLASSIFICATION_RESTRICTED,
        "retention_days": 3650,
        "export_action": EXPORT_ACTION_DENY,
        "auto_redact_pii": True,
        "require_export_audit": True,
    },
    {
        "entity_type": ENTITY_PM_DATA,
        "default_classification": CLASSIFICATION_INTERNAL,
        "retention_days": 730,
        "export_action": EXPORT_ACTION_ALLOW,
        "auto_redact_pii": False,
        "require_export_audit": False,
    },
]





async def ensure_default_policies(db: AsyncSession, *, created_by: str | None = None) -> int:
    """Seed the default platform-wide policies (idempotent).

    Returns the number of policies created (0 if already exists).
    """
    created = 0
    for spec in _DEFAULT_POLICIES:
        existing = await db.execute(
            select(DataClassificationPolicy).where(
                DataClassificationPolicy.entity_type == spec["entity_type"],
                DataClassificationPolicy.project_id.is_(None),
                DataClassificationPolicy.is_active.is_(True),
            )
        )
        if existing.scalars().first():
            continue
        policy = DataClassificationPolicy(
            entity_type=spec["entity_type"],
            default_classification=spec["default_classification"],
            retention_days=spec.get("retention_days"),
            export_action=spec["export_action"],
            auto_redact_pii=spec.get("auto_redact_pii", False),
            require_export_audit=spec.get("require_export_audit", True),
            created_by=created_by,
        )
        db.add(policy)
        created += 1
    await db.flush()
    return created


async def get_policy(
    db: AsyncSession,
    entity_type: str,
    *,
    project_id: str | None = None,
) -> DataClassificationPolicy | None:
    """Return the active policy for *entity_type*, preferring project-scoped over platform-wide.

    Returns ``None`` if no policy is defined.
    """
    if project_id:
        result = await db.execute(
            select(DataClassificationPolicy).where(
                DataClassificationPolicy.entity_type == entity_type,
                DataClassificationPolicy.project_id == project_id,
                DataClassificationPolicy.is_active.is_(True),
            )
        )
        policy = result.scalars().first()
        if policy:
            return policy

    result = await db.execute(
        select(DataClassificationPolicy).where(
            DataClassificationPolicy.entity_type == entity_type,
            DataClassificationPolicy.project_id.is_(None),
            DataClassificationPolicy.is_active.is_(True),
        )
    )
    return result.scalars().first()
