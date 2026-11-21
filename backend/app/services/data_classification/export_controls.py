"""Export controls and the redaction audit log."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.security.data_classification import (
    CLASSIFICATION_INTERNAL,
    CLASSIFICATION_RESTRICTED,
    EXPORT_ACTION_ALLOW,
    EXPORT_ACTION_DENY,
    EXPORT_ACTION_REDACT,
    DataRedactionLog,
)
from ..model_gateway.data_policy.classification import classification_rank
from .pii import detect_and_redact_pii
from .policies import get_policy
from .tags import get_classification


async def check_export_allowed(
    db: AsyncSession,
    entity_type: str,
    *,
    project_id: str | None = None,
    classification: str | None = None,
) -> tuple[bool, str]:
    """Check whether export of *entity_type* is allowed per active policy.

    Returns:
        ``(allowed: bool, action: str)`` — action is allow | redact | deny
    """
    policy = await get_policy(db, entity_type, project_id=project_id)
    if not policy:
        return True, EXPORT_ACTION_ALLOW

    # Escalate if effective classification is higher than policy expects
    rank, policy_rank = classification_rank(classification), classification_rank(policy.default_classification)
    if rank is not None and policy_rank is not None and rank > policy_rank:
        # More sensitive than default — deny from Restricted upwards (any level ranked at or above it)
        if rank >= (classification_rank(CLASSIFICATION_RESTRICTED) or 0):
            return False, EXPORT_ACTION_DENY

    return policy.export_action != EXPORT_ACTION_DENY, policy.export_action


async def apply_export_classification(
    db: AsyncSession,
    payload: Any,
    entity_type: str,
    entity_id: str,
    *,
    actor_user_id: str | None = None,
    project_id: str | None = None,
) -> tuple[Any, str]:
    """Apply classification policy to a payload at export time.

    Returns:
        ``(processed_payload, action_taken)`` where action is allow | redact | deny.
        If deny, raises ``HTTPException(403)``.
    """
    tag = await get_classification(db, entity_type, entity_id)
    effective_classification = tag.classification if tag else None

    allowed, action = await check_export_allowed(
        db, entity_type, project_id=project_id, classification=effective_classification
    )

    if not allowed:
        await _deny_export(db, entity_type, entity_id, effective_classification, action,
                           actor_user_id=actor_user_id, project_id=project_id)

    if action == EXPORT_ACTION_REDACT:
        processed = await _redact_export(db, payload, entity_type, entity_id, effective_classification,
                                         actor_user_id=actor_user_id, project_id=project_id)
        return processed, action

    return payload, action


async def _deny_export(
    db: AsyncSession,
    entity_type: str,
    entity_id: str,
    effective_classification: str | None,
    action: str,
    *,
    actor_user_id: str | None,
    project_id: str | None,
) -> None:
    """Log the denial, then refuse the export."""
    log = DataRedactionLog(
        entity_type=entity_type,
        entity_id=entity_id,
        redaction_reason="export_denied",
        classification=effective_classification or CLASSIFICATION_INTERNAL,
        pii_types_redacted=[],
        redacted_fields=[],
        actor_user_id=actor_user_id,
        context_json={"action": action, "project_id": project_id},
    )
    db.add(log)
    await db.flush()
    raise HTTPException(
        status_code=403,
        detail=f"Export denied for entity_type={entity_type!r} at classification level "
        f"{effective_classification!r}.",
    )


async def _redact_export(
    db: AsyncSession,
    payload: Any,
    entity_type: str,
    entity_id: str,
    effective_classification: str | None,
    *,
    actor_user_id: str | None,
    project_id: str | None,
) -> Any:
    processed, detected_pii, paths = detect_and_redact_pii(payload)

    # Also apply credential scrubbing
    from app.services.credential_governance.scrubbing import scrub_secrets_from_payload

    processed, secret_paths = scrub_secrets_from_payload(processed)

    all_paths = paths + secret_paths
    if all_paths:
        log = DataRedactionLog(
            entity_type=entity_type,
            entity_id=entity_id,
            redaction_reason="export",
            classification=effective_classification or CLASSIFICATION_INTERNAL,
            pii_types_redacted=detected_pii,
            redacted_fields=all_paths,
            actor_user_id=actor_user_id,
            context_json={"project_id": project_id},
        )
        db.add(log)
        await db.flush()
    return processed





async def list_redaction_logs(
    db: AsyncSession,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    redaction_reason: str | None = None,
    limit: int = 100,
) -> list[DataRedactionLog]:
    query = select(DataRedactionLog)
    if entity_type:
        query = query.where(DataRedactionLog.entity_type == entity_type)
    if entity_id:
        query = query.where(DataRedactionLog.entity_id == entity_id)
    if redaction_reason:
        query = query.where(DataRedactionLog.redaction_reason == redaction_reason)
    query = query.order_by(DataRedactionLog.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())
