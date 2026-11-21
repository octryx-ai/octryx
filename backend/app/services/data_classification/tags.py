"""Classification tags: create, update and query."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.security.data_classification import (
    ALL_ENTITY_TYPES,
    CLASSIFICATION_INTERNAL,
    DataClassificationTag,
)
from ..model_gateway.data_policy.classification import DATA_CLASSIFICATION_ORDER


async def classify_entity(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    classification: str = CLASSIFICATION_INTERNAL,
    project_id: str | None = None,
    pii_types: list[str] | None = None,
    retention_days_override: int | None = None,
    data_residency: str | None = None,
    sensitivity_tags: list[str] | None = None,
    notes: str | None = None,
    classified_by: str | None = None,
) -> DataClassificationTag:
    """Create or update the classification tag for an entity.

    Args:
        entity_type: Must be one of ``ALL_ENTITY_TYPES``.
        entity_id: ID of the record being classified.
        classification: One of the registered levels (``DATA_CLASSIFICATION_ORDER``).
        ...

    Raises:
        ValueError: If entity_type or classification is invalid.
    """
    _check_tag_values(entity_type, classification)

    result = await db.execute(
        select(DataClassificationTag).where(
            DataClassificationTag.entity_type == entity_type,
            DataClassificationTag.entity_id == entity_id,
        )
    )
    tag = result.scalars().first()
    values = {
        "classification": classification,
        "project_id": project_id,
        "pii_types": pii_types,
        "retention_days_override": retention_days_override,
        "data_residency": data_residency,
        "sensitivity_tags": sensitivity_tags,
        "notes": notes,
        "classified_by": classified_by,
    }

    if tag:
        _update_tag(tag, **values)
    else:
        tag = _new_tag(entity_type=entity_type, entity_id=entity_id, **values)
        db.add(tag)

    await db.flush()
    return tag


def _check_tag_values(entity_type: str, classification: str) -> None:
    if entity_type not in ALL_ENTITY_TYPES:
        raise ValueError(f"Invalid entity_type {entity_type!r}. Must be one of {sorted(ALL_ENTITY_TYPES)}")
    if classification not in DATA_CLASSIFICATION_ORDER:
        levels = tuple(DATA_CLASSIFICATION_ORDER)
        raise ValueError(f"Invalid classification {classification!r}. Must be one of {levels}")


def _update_tag(
    tag: DataClassificationTag,
    *,
    classification: str,
    project_id: str | None,
    pii_types: list[str] | None,
    retention_days_override: int | None,
    data_residency: str | None,
    sensitivity_tags: list[str] | None,
    notes: str | None,
    classified_by: str | None,
) -> None:
    tag.classification = classification
    tag.project_id = project_id if project_id is not None else tag.project_id
    tag.pii_detected = bool(pii_types)
    tag.pii_types = pii_types or []
    tag.retention_days_override = retention_days_override
    tag.data_residency = data_residency
    tag.sensitivity_tags = sensitivity_tags or tag.sensitivity_tags
    tag.notes = notes or tag.notes
    tag.classified_by = classified_by or tag.classified_by


def _new_tag(
    *,
    entity_type: str,
    entity_id: str,
    classification: str,
    project_id: str | None,
    pii_types: list[str] | None,
    retention_days_override: int | None,
    data_residency: str | None,
    sensitivity_tags: list[str] | None,
    notes: str | None,
    classified_by: str | None,
) -> DataClassificationTag:
    return DataClassificationTag(
        entity_type=entity_type,
        entity_id=entity_id,
        classification=classification,
        project_id=project_id,
        pii_detected=bool(pii_types),
        pii_types=pii_types or [],
        retention_days_override=retention_days_override,
        data_residency=data_residency,
        sensitivity_tags=sensitivity_tags or [],
        notes=notes,
        classified_by=classified_by,
    )


async def get_classification(
    db: AsyncSession,
    entity_type: str,
    entity_id: str,
) -> DataClassificationTag | None:
    """Return the classification tag for a specific entity, or None."""
    result = await db.execute(
        select(DataClassificationTag).where(
            DataClassificationTag.entity_type == entity_type,
            DataClassificationTag.entity_id == entity_id,
        )
    )
    return result.scalars().first()


async def list_classification_tags(
    db: AsyncSession,
    *,
    entity_type: str | None = None,
    project_id: str | None = None,
    classification: str | None = None,
    pii_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[DataClassificationTag]:
    """Query classification tags with optional filters."""
    query = select(DataClassificationTag)
    if entity_type:
        query = query.where(DataClassificationTag.entity_type == entity_type)
    if project_id:
        query = query.where(DataClassificationTag.project_id == project_id)
    if classification:
        query = query.where(DataClassificationTag.classification == classification)
    if pii_only:
        query = query.where(DataClassificationTag.pii_detected.is_(True))
    query = query.order_by(DataClassificationTag.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())
