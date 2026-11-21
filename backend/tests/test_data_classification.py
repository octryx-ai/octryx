"""Tests for Data Classification, Retention, and Redaction service.

Covers:
  - ensure_default_policies: seeds all entity types, idempotent
  - get_policy: returns platform-wide policy, project override preferred
  - classify_entity: creates tag, update existing tag
  - classify_entity: rejects invalid entity_type
  - classify_entity: rejects invalid classification level
  - get_classification: returns tag, None for unknown entity
  - list_classification_tags: filtered by entity_type, classification, pii_only
  - pii_redact_text: detects and redacts email, phone, SSN, credit card, IBAN, IP
  - pii_redact_text: unchanged when no PII found
  - detect_and_redact_pii: recursive redaction in nested dict
  - detect_and_redact_pii: recursive redaction in list
  - check_export_allowed: allow / redact / deny per policy
  - check_export_allowed: escalate to deny for SECRET classification
  - apply_export_classification: allow path returns payload unchanged
  - apply_export_classification: redact path applies PII + secret scrubbing and logs
  - apply_export_classification: deny path raises HTTP 403
  - list_redaction_logs: filtered by entity and reason
  - HCM / Legal data classified as RESTRICTED and deny-by-default
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security.data_classification import (
    CLASSIFICATION_CONFIDENTIAL,
    CLASSIFICATION_INTERNAL,
    CLASSIFICATION_RESTRICTED,
    ENTITY_CONNECTOR_PAYLOAD,
    ENTITY_HCM_DATA,
    ENTITY_KNOWLEDGE_MAP,
    ENTITY_LEGAL_DATA,
    ENTITY_MESSAGE,
    ENTITY_SESSION,
    ENTITY_TRACE_SPAN,
    EXPORT_ACTION_ALLOW,
    EXPORT_ACTION_DENY,
    EXPORT_ACTION_REDACT,
    PII_EMAIL,
    PII_PHONE,
    PII_SSN,
)
from app.services.data_classification.policies import ensure_default_policies, get_policy
from app.services.data_classification.tags import classify_entity, get_classification, list_classification_tags
from tests.data_classification_support import _uid

# ---------------------------------------------------------------------------
# Policy management
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_default_policies_seeds_all_entity_types(db: AsyncSession, auth_user):
    created = await ensure_default_policies(db, created_by=auth_user.id)
    assert created > 0
    # Second call is idempotent — no new policies created
    created2 = await ensure_default_policies(db, created_by=auth_user.id)
    assert created2 == 0


@pytest.mark.asyncio
async def test_get_policy_returns_platform_default(db: AsyncSession, auth_user):
    await ensure_default_policies(db, created_by=auth_user.id)
    policy = await get_policy(db, ENTITY_SESSION)
    assert policy is not None
    assert policy.entity_type == ENTITY_SESSION
    assert policy.export_action == EXPORT_ACTION_REDACT


@pytest.mark.asyncio
async def test_get_policy_returns_none_for_unknown_type(db: AsyncSession, auth_user):
    await ensure_default_policies(db, created_by=auth_user.id)
    policy = await get_policy(db, "nonexistent_type")
    assert policy is None


@pytest.mark.asyncio
async def test_get_policy_connector_is_deny_by_default(db: AsyncSession, auth_user):
    await ensure_default_policies(db, created_by=auth_user.id)
    policy = await get_policy(db, ENTITY_CONNECTOR_PAYLOAD)
    assert policy is not None
    assert policy.export_action == EXPORT_ACTION_DENY


@pytest.mark.asyncio
async def test_get_policy_hcm_is_restricted_deny(db: AsyncSession, auth_user):
    await ensure_default_policies(db, created_by=auth_user.id)
    policy = await get_policy(db, ENTITY_HCM_DATA)
    assert policy is not None
    assert policy.default_classification == CLASSIFICATION_RESTRICTED
    assert policy.export_action == EXPORT_ACTION_DENY
    assert policy.auto_redact_pii is True


@pytest.mark.asyncio
async def test_get_policy_legal_data_restricted_deny(db: AsyncSession, auth_user):
    await ensure_default_policies(db, created_by=auth_user.id)
    policy = await get_policy(db, ENTITY_LEGAL_DATA)
    assert policy is not None
    assert policy.default_classification == CLASSIFICATION_RESTRICTED
    assert policy.export_action == EXPORT_ACTION_DENY


@pytest.mark.asyncio
async def test_get_policy_knowledge_map_is_allow(db: AsyncSession, auth_user):
    await ensure_default_policies(db, created_by=auth_user.id)
    policy = await get_policy(db, ENTITY_KNOWLEDGE_MAP)
    assert policy is not None
    assert policy.export_action == EXPORT_ACTION_ALLOW


# ---------------------------------------------------------------------------
# Tag management
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_entity_creates_tag(db: AsyncSession, auth_user):
    entity_id = _uid()
    tag = await classify_entity(
        db,
        entity_type=ENTITY_SESSION,
        entity_id=entity_id,
        classification=CLASSIFICATION_CONFIDENTIAL,
        pii_types=[PII_EMAIL, PII_PHONE],
        classified_by=auth_user.id,
    )
    assert tag.id is not None
    assert tag.classification == CLASSIFICATION_CONFIDENTIAL
    assert tag.pii_detected is True
    assert PII_EMAIL in tag.pii_types
    assert PII_PHONE in tag.pii_types


@pytest.mark.asyncio
async def test_classify_entity_update_existing(db: AsyncSession, auth_user):
    entity_id = _uid()
    tag = await classify_entity(
        db,
        entity_type=ENTITY_MESSAGE,
        entity_id=entity_id,
        classification=CLASSIFICATION_INTERNAL,
        classified_by=auth_user.id,
    )
    # Upgrade classification
    updated = await classify_entity(
        db,
        entity_type=ENTITY_MESSAGE,
        entity_id=entity_id,
        classification=CLASSIFICATION_RESTRICTED,
        pii_types=[PII_SSN],
        classified_by=auth_user.id,
    )
    assert updated.id == tag.id
    assert updated.classification == CLASSIFICATION_RESTRICTED
    assert PII_SSN in updated.pii_types


@pytest.mark.asyncio
async def test_classify_entity_invalid_entity_type(db: AsyncSession):
    with pytest.raises(ValueError, match="Invalid entity_type"):
        await classify_entity(db, entity_type="foobar", entity_id=_uid())


@pytest.mark.asyncio
async def test_classify_entity_invalid_classification(db: AsyncSession):
    with pytest.raises(ValueError, match="Invalid classification"):
        await classify_entity(
            db,
            entity_type=ENTITY_SESSION,
            entity_id=_uid(),
            classification="ultra_secret",
        )


@pytest.mark.asyncio
async def test_get_classification_returns_tag(db: AsyncSession, auth_user):
    entity_id = _uid()
    await classify_entity(
        db, entity_type=ENTITY_TRACE_SPAN, entity_id=entity_id,
        classification=CLASSIFICATION_CONFIDENTIAL, classified_by=auth_user.id,
    )
    tag = await get_classification(db, ENTITY_TRACE_SPAN, entity_id)
    assert tag is not None
    assert tag.classification == CLASSIFICATION_CONFIDENTIAL


@pytest.mark.asyncio
async def test_get_classification_returns_none_for_unknown(db: AsyncSession):
    tag = await get_classification(db, ENTITY_SESSION, _uid())
    assert tag is None


@pytest.mark.asyncio
async def test_list_classification_tags_filtered_by_entity_type(db: AsyncSession, auth_user):
    e1 = _uid()
    e2 = _uid()
    await classify_entity(db, entity_type=ENTITY_SESSION, entity_id=e1, classified_by=auth_user.id)
    await classify_entity(db, entity_type=ENTITY_MESSAGE, entity_id=e2, classified_by=auth_user.id)
    tags = await list_classification_tags(db, entity_type=ENTITY_SESSION)
    entity_types = {t.entity_type for t in tags}
    assert entity_types == {ENTITY_SESSION}


@pytest.mark.asyncio
async def test_list_classification_tags_pii_only_filter(db: AsyncSession, auth_user):
    e1 = _uid()
    e2 = _uid()
    await classify_entity(db, entity_type=ENTITY_MESSAGE, entity_id=e1,
                          pii_types=[PII_EMAIL], classified_by=auth_user.id)
    await classify_entity(db, entity_type=ENTITY_MESSAGE, entity_id=e2,
                          classified_by=auth_user.id)  # no PII
    tags = await list_classification_tags(db, entity_type=ENTITY_MESSAGE, pii_only=True)
    assert all(t.pii_detected for t in tags)
    pii_ids = {t.entity_id for t in tags}
    assert e1 in pii_ids
    assert e2 not in pii_ids
