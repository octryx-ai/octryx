"""Tests for Credential and Secret Governance.

Covers:
  - Scope binding creation (valid entity types, duplicate prevention)
  - Scope binding revocation (soft-delete, double-revoke error)
  - Scoped secret access: allowed when binding exists, denied when not
  - Audit log written for bind, revoke, read, denied
  - Export scrubbing: secrets stripped from payloads (keys + nested)
  - scrub_and_audit_export: scrubbed paths audited
  - list_bindings_for_secret / list_bindings_for_entity
  - list_audit_log with filters
  - scrub_secrets_from_payload unit tests (no DB)
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security.credential_governance import (
    AUDIT_ACTION_BIND,
    AUDIT_ACTION_REVOKE,
    SCOPE_ENTITY_AGENT,
    SCOPE_ENTITY_CONNECTOR,
    SCOPE_ENTITY_DOMAIN_PACK,
    SCOPE_ENTITY_FLOW,
    SCOPE_ENTITY_MCP_SERVER,
    SCOPE_PERM_READ_ONLY,
)
from app.services.credential_governance.audit import list_audit_log
from app.services.credential_governance.service import create_scope_binding, revoke_scope_binding
from tests.credential_governance_support import _make_secret, _uid

# ---------------------------------------------------------------------------
# Tests: Scope binding creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_scope_binding_success(db: AsyncSession, auth_user):
    secret = await _make_secret(db)
    binding = await create_scope_binding(
        db,
        secret_id=secret.id,
        entity_type=SCOPE_ENTITY_AGENT,
        entity_id=_uid(),
        entity_label="fraud-detection-agent",
        permission=SCOPE_PERM_READ_ONLY,
        reason="Needs API key for third-party risk service",
        created_by=auth_user.id,
    )
    assert binding.id is not None
    assert binding.is_active is True
    assert binding.permission == SCOPE_PERM_READ_ONLY


@pytest.mark.asyncio
async def test_create_scope_binding_all_entity_types(db: AsyncSession, auth_user):
    """All valid entity types must be accepted."""
    secret = await _make_secret(db)
    for entity_type in [
        SCOPE_ENTITY_AGENT, SCOPE_ENTITY_FLOW, SCOPE_ENTITY_CONNECTOR,
        SCOPE_ENTITY_MCP_SERVER, SCOPE_ENTITY_DOMAIN_PACK,
    ]:
        b = await create_scope_binding(
            db,
            secret_id=secret.id,
            entity_type=entity_type,
            entity_id=_uid(),
            created_by=auth_user.id,
        )
        assert b.entity_type == entity_type


@pytest.mark.asyncio
async def test_create_scope_binding_invalid_entity_type(db: AsyncSession, auth_user):
    secret = await _make_secret(db)
    with pytest.raises(ValueError, match="Invalid entity_type"):
        await create_scope_binding(
            db,
            secret_id=secret.id,
            entity_type="robot",
            entity_id=_uid(),
            created_by=auth_user.id,
        )


@pytest.mark.asyncio
async def test_create_scope_binding_duplicate_raises(db: AsyncSession, auth_user):
    secret = await _make_secret(db)
    entity_id = _uid()
    await create_scope_binding(
        db, secret_id=secret.id, entity_type=SCOPE_ENTITY_AGENT,
        entity_id=entity_id, created_by=auth_user.id,
    )
    with pytest.raises(ValueError, match="Active binding already exists"):
        await create_scope_binding(
            db, secret_id=secret.id, entity_type=SCOPE_ENTITY_AGENT,
            entity_id=entity_id, created_by=auth_user.id,
        )


@pytest.mark.asyncio
async def test_create_binding_writes_audit_log(db: AsyncSession, auth_user):
    secret = await _make_secret(db)
    entity_id = _uid()
    await create_scope_binding(
        db, secret_id=secret.id, entity_type=SCOPE_ENTITY_FLOW,
        entity_id=entity_id, created_by=auth_user.id,
    )
    logs = await list_audit_log(db, secret_id=secret.id, action=AUDIT_ACTION_BIND)
    assert len(logs) == 1
    assert logs[0].outcome == "success"


# ---------------------------------------------------------------------------
# Tests: Scope binding revocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_scope_binding_success(db: AsyncSession, auth_user):
    secret = await _make_secret(db)
    binding = await create_scope_binding(
        db, secret_id=secret.id, entity_type=SCOPE_ENTITY_CONNECTOR,
        entity_id=_uid(), created_by=auth_user.id,
    )
    revoked = await revoke_scope_binding(db, binding_id=binding.id, revoked_by=auth_user.id)
    assert revoked.is_active is False
    assert revoked.revoked_at is not None


@pytest.mark.asyncio
async def test_revoke_scope_binding_double_revoke_raises(db: AsyncSession, auth_user):
    secret = await _make_secret(db)
    binding = await create_scope_binding(
        db, secret_id=secret.id, entity_type=SCOPE_ENTITY_CONNECTOR,
        entity_id=_uid(), created_by=auth_user.id,
    )
    await revoke_scope_binding(db, binding_id=binding.id, revoked_by=auth_user.id)
    with pytest.raises(ValueError, match="already revoked"):
        await revoke_scope_binding(db, binding_id=binding.id, revoked_by=auth_user.id)


@pytest.mark.asyncio
async def test_revoke_writes_audit_log(db: AsyncSession, auth_user):
    secret = await _make_secret(db)
    binding = await create_scope_binding(
        db, secret_id=secret.id, entity_type=SCOPE_ENTITY_MCP_SERVER,
        entity_id=_uid(), created_by=auth_user.id,
    )
    await revoke_scope_binding(db, binding_id=binding.id, revoked_by=auth_user.id)
    logs = await list_audit_log(db, secret_id=secret.id, action=AUDIT_ACTION_REVOKE)
    assert len(logs) == 1
