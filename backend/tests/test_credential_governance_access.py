"""Scoped secret access serves only bound, unrevoked secrets and audits denials, and export payloads are scrubbed of secrets with the scrub audited."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security.credential_governance import (
    AUDIT_ACTION_EXPORT_SCRUB,
    AUDIT_ACTION_READ,
    SCOPE_ENTITY_AGENT,
    SCOPE_ENTITY_FLOW,
)
from app.services.credential_governance.audit import list_audit_log, scrub_and_audit_export
from app.services.credential_governance.scrubbing import scrub_secrets_from_payload
from app.services.credential_governance.service import (
    create_scope_binding,
    get_secret_value_for_entity,
    revoke_scope_binding,
)
from tests.credential_governance_support import _make_secret, _uid

# ---------------------------------------------------------------------------
# Tests: Scoped secret access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_secret_value_for_entity_success(db: AsyncSession, auth_user):
    secret = await _make_secret(db)
    entity_id = _uid()
    await create_scope_binding(
        db, secret_id=secret.id, entity_type=SCOPE_ENTITY_AGENT,
        entity_id=entity_id, created_by=auth_user.id,
    )
    value = await get_secret_value_for_entity(
        db, secret_id=secret.id, entity_type=SCOPE_ENTITY_AGENT,
        entity_id=entity_id, actor_user_id=auth_user.id,
    )
    assert value == "super-secret-value-123"


@pytest.mark.asyncio
async def test_get_secret_value_no_binding_raises(db: AsyncSession, auth_user):
    secret = await _make_secret(db)
    with pytest.raises(PermissionError, match="no_active_binding|does not have"):
        await get_secret_value_for_entity(
            db, secret_id=secret.id, entity_type=SCOPE_ENTITY_AGENT,
            entity_id=_uid(), actor_user_id=auth_user.id,
        )


@pytest.mark.asyncio
async def test_get_secret_value_after_revoke_raises(db: AsyncSession, auth_user):
    secret = await _make_secret(db)
    entity_id = _uid()
    binding = await create_scope_binding(
        db, secret_id=secret.id, entity_type=SCOPE_ENTITY_AGENT,
        entity_id=entity_id, created_by=auth_user.id,
    )
    await revoke_scope_binding(db, binding_id=binding.id, revoked_by=auth_user.id)
    with pytest.raises(PermissionError):
        await get_secret_value_for_entity(
            db, secret_id=secret.id, entity_type=SCOPE_ENTITY_AGENT,
            entity_id=entity_id, actor_user_id=auth_user.id,
        )


@pytest.mark.asyncio
async def test_denied_access_writes_audit_log(db: AsyncSession, auth_user):
    secret = await _make_secret(db)
    entity_id = _uid()
    with pytest.raises(PermissionError):
        await get_secret_value_for_entity(
            db, secret_id=secret.id, entity_type=SCOPE_ENTITY_FLOW,
            entity_id=entity_id, actor_user_id=auth_user.id,
        )
    logs = await list_audit_log(db, secret_id=secret.id, action=AUDIT_ACTION_READ)
    denied = [log for log in logs if log.outcome == "denied"]
    assert len(denied) == 1


# ---------------------------------------------------------------------------
# Tests: Export scrubbing (pure / no DB)
# ---------------------------------------------------------------------------


def test_scrub_secrets_from_payload_flat_dict():
    payload = {
        "name": "My Connector",
        "api_key": "should-be-redacted",
        "url": "https://example.com",
        "password": "also-redacted",
    }
    scrubbed, paths = scrub_secrets_from_payload(payload)
    assert scrubbed["api_key"] == "[REDACTED]"
    assert scrubbed["password"] == "[REDACTED]"
    assert scrubbed["name"] == "My Connector"
    assert scrubbed["url"] == "https://example.com"
    assert "api_key" in paths
    assert "password" in paths


def test_scrub_secrets_from_payload_nested():
    payload = {
        "agent": {
            "name": "fraud-agent",
            "config": {
                "token": "top-secret",
                "model": "gpt-4",
            },
        }
    }
    scrubbed, paths = scrub_secrets_from_payload(payload)
    assert scrubbed["agent"]["config"]["token"] == "[REDACTED]"
    assert scrubbed["agent"]["config"]["model"] == "gpt-4"
    assert "agent.config.token" in paths


def test_scrub_secrets_from_payload_list_of_dicts():
    payload = [
        {"name": "item1", "secret": "hidden"},
        {"name": "item2", "url": "ok"},
    ]
    scrubbed, paths = scrub_secrets_from_payload(payload)
    assert scrubbed[0]["secret"] == "[REDACTED]"
    assert scrubbed[1]["name"] == "item2"


def test_scrub_secrets_from_payload_encrypted_value():
    payload = {"encrypted_value": "fernet:abc123", "other": "safe"}
    scrubbed, paths = scrub_secrets_from_payload(payload)
    assert scrubbed["encrypted_value"] == "[REDACTED]"
    assert scrubbed["other"] == "safe"


def test_scrub_secrets_from_payload_no_secrets():
    payload = {"name": "clean", "url": "https://example.com", "config": {"model": "gpt-4"}}
    scrubbed, paths = scrub_secrets_from_payload(payload)
    assert scrubbed == payload
    assert paths == []


@pytest.mark.asyncio
async def test_scrub_and_audit_export_writes_audit(db: AsyncSession, auth_user):
    payload = {"agent": "test", "api_key": "leak", "config": {"token": "also-leak"}}
    scrubbed = await scrub_and_audit_export(
        db, payload=payload, actor_user_id=auth_user.id, export_context="project_backup"
    )
    assert scrubbed["api_key"] == "[REDACTED]"
    logs = await list_audit_log(db, action=AUDIT_ACTION_EXPORT_SCRUB)
    assert len(logs) >= 1
    assert logs[0].context_json["export_context"] == "project_backup"
    assert "api_key" in logs[0].context_json["scrubbed_paths"]
