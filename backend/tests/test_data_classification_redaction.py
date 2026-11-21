"""PII detection and redaction in text and nested payloads, the export allow/redact/deny decision with its SECRET escalation, and the redaction log."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security.data_classification import (
    CLASSIFICATION_INTERNAL,
    CLASSIFICATION_PUBLIC,
    CLASSIFICATION_SECRET,
    ENTITY_CONNECTOR_PAYLOAD,
    ENTITY_KNOWLEDGE_MAP,
    ENTITY_SESSION,
    EXPORT_ACTION_ALLOW,
    EXPORT_ACTION_DENY,
    EXPORT_ACTION_REDACT,
    PII_EMAIL,
    PII_IP_ADDRESS,
    PII_SSN,
)
from app.services.data_classification.export_controls import (
    apply_export_classification,
    check_export_allowed,
    list_redaction_logs,
)
from app.services.data_classification.pii import detect_and_redact_pii, pii_redact_text
from app.services.data_classification.policies import ensure_default_policies
from app.services.data_classification.tags import classify_entity
from tests.data_classification_support import _uid

# ---------------------------------------------------------------------------
# PII detection and redaction
# ---------------------------------------------------------------------------


def test_pii_redact_text_email():
    text = "Contact us at john.doe@example.com for support."
    redacted, found = pii_redact_text(text)
    assert "[EMAIL]" in redacted
    assert "john.doe@example.com" not in redacted
    assert PII_EMAIL in found


def test_pii_redact_text_ssn():
    text = "SSN: 123-45-6789 on file."
    redacted, found = pii_redact_text(text)
    assert "[SSN]" in redacted
    assert "123-45-6789" not in redacted
    assert PII_SSN in found


def test_pii_redact_text_ip_address():
    text = "Request from 192.168.1.100 blocked."
    redacted, found = pii_redact_text(text)
    assert "[IP]" in redacted
    assert "192.168.1.100" not in redacted
    assert PII_IP_ADDRESS in found


def test_pii_redact_text_no_pii():
    text = "The meeting is on Monday at 10am."
    redacted, found = pii_redact_text(text)
    assert redacted == text
    assert found == []


def test_pii_redact_text_selective_types():
    text = "Email: test@example.com, Phone: +41441234567"
    redacted, found = pii_redact_text(text, pii_types=[PII_EMAIL])
    assert "[EMAIL]" in redacted
    assert PII_EMAIL in found
    # Phone should NOT be redacted when only EMAIL requested
    assert "+41441234567" in redacted


def test_detect_and_redact_pii_nested_dict():
    payload = {
        "user": {"email": "jane@example.com", "role": "admin"},
        "summary": "call from 10.0.0.1",
    }
    result, detected, paths = detect_and_redact_pii(payload)
    assert "[EMAIL]" in result["user"]["email"]
    assert "[IP]" in result["summary"]
    assert PII_EMAIL in detected
    assert PII_IP_ADDRESS in detected
    assert any("email" in p for p in paths)


def test_detect_and_redact_pii_list():
    payload = [
        {"note": "Contact alice@example.org"},
        {"note": "No sensitive data here"},
    ]
    result, detected, paths = detect_and_redact_pii(payload)
    assert "[EMAIL]" in result[0]["note"]
    assert result[1]["note"] == "No sensitive data here"
    assert PII_EMAIL in detected


# ---------------------------------------------------------------------------
# Export controls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_export_allowed_allow_policy(db: AsyncSession, auth_user):
    await ensure_default_policies(db, created_by=auth_user.id)
    allowed, action = await check_export_allowed(db, ENTITY_KNOWLEDGE_MAP)
    assert allowed is True
    assert action == EXPORT_ACTION_ALLOW


@pytest.mark.asyncio
async def test_check_export_allowed_redact_policy(db: AsyncSession, auth_user):
    await ensure_default_policies(db, created_by=auth_user.id)
    allowed, action = await check_export_allowed(db, ENTITY_SESSION)
    assert allowed is True
    assert action == EXPORT_ACTION_REDACT


@pytest.mark.asyncio
async def test_check_export_allowed_deny_policy(db: AsyncSession, auth_user):
    await ensure_default_policies(db, created_by=auth_user.id)
    allowed, action = await check_export_allowed(db, ENTITY_CONNECTOR_PAYLOAD)
    assert allowed is False
    assert action == EXPORT_ACTION_DENY


@pytest.mark.asyncio
async def test_check_export_denied_for_secret_classification_escalation(db: AsyncSession, auth_user):
    await ensure_default_policies(db, created_by=auth_user.id)
    # knowledge_map default is ALLOW, but SECRET classification escalates to deny
    allowed, action = await check_export_allowed(
        db, ENTITY_KNOWLEDGE_MAP, classification=CLASSIFICATION_SECRET
    )
    assert allowed is False
    assert action == EXPORT_ACTION_DENY


@pytest.mark.asyncio
async def test_apply_export_classification_allow_path(db: AsyncSession, auth_user):
    await ensure_default_policies(db, created_by=auth_user.id)
    entity_id = _uid()
    await classify_entity(
        db, entity_type=ENTITY_KNOWLEDGE_MAP, entity_id=entity_id,
        classification=CLASSIFICATION_PUBLIC, classified_by=auth_user.id,
    )
    payload = {"key": "some knowledge", "value": "safe content"}
    result, action = await apply_export_classification(
        db, payload, ENTITY_KNOWLEDGE_MAP, entity_id, actor_user_id=auth_user.id,
    )
    assert action == EXPORT_ACTION_ALLOW
    assert result == payload


@pytest.mark.asyncio
async def test_apply_export_classification_redact_path(db: AsyncSession, auth_user):
    await ensure_default_policies(db, created_by=auth_user.id)
    entity_id = _uid()
    await classify_entity(
        db, entity_type=ENTITY_SESSION, entity_id=entity_id,
        classification=CLASSIFICATION_INTERNAL, pii_types=[PII_EMAIL],
        classified_by=auth_user.id,
    )
    payload = {"summary": "Sent by admin@example.com", "api_key": "s3cr3t"}
    result, action = await apply_export_classification(
        db, payload, ENTITY_SESSION, entity_id, actor_user_id=auth_user.id,
    )
    assert action == EXPORT_ACTION_REDACT
    assert "[EMAIL]" in result["summary"]
    assert result["api_key"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_apply_export_classification_deny_raises_403(db: AsyncSession, auth_user):
    await ensure_default_policies(db, created_by=auth_user.id)
    entity_id = _uid()
    await classify_entity(
        db, entity_type=ENTITY_CONNECTOR_PAYLOAD, entity_id=entity_id,
        classified_by=auth_user.id,
    )
    with pytest.raises(HTTPException) as exc_info:
        await apply_export_classification(
            db, {"data": "sensitive"}, ENTITY_CONNECTOR_PAYLOAD, entity_id,
            actor_user_id=auth_user.id,
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_list_redaction_logs_filtered(db: AsyncSession, auth_user):
    await ensure_default_policies(db, created_by=auth_user.id)
    entity_id = _uid()
    await classify_entity(
        db, entity_type=ENTITY_SESSION, entity_id=entity_id,
        classified_by=auth_user.id,
    )
    payload = {"note": "call test@example.com"}
    await apply_export_classification(
        db, payload, ENTITY_SESSION, entity_id, actor_user_id=auth_user.id,
    )
    logs = await list_redaction_logs(db, entity_type=ENTITY_SESSION, entity_id=entity_id)
    assert len(logs) >= 1
    assert logs[0].entity_type == ENTITY_SESSION
