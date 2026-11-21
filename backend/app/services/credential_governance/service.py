"""Credential and Secret Governance Service.

Provides:
  - Scope binding lifecycle (create, revoke, list)
  - Least-privilege access enforcement: assert entity has an active binding
    before a secret value is returned
  - Audit logging for all governance events
  - Export scrubbing: strip raw secrets from any dict before it leaves the platform
  - Helper: `scrub_secrets_from_payload` — recursive dict scrubber used by
    data_transfer exports, trace serialization, and domain pack exports

Scrubbing lives in ``scrubbing.py`` and the audit trail in ``audit.py``; both stay importable from here.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.security.credential_governance import (
    AUDIT_ACTION_BIND,
    AUDIT_ACTION_READ,
    AUDIT_ACTION_REVOKE,
    SCOPE_ENTITY_TYPES,
    SCOPE_PERM_READ_ONLY,
    SecretScopeBinding,
)
from ...models.security.secret import StoredSecret
from ...services.secret.service import decrypt_secret
from ...time_utils import utc_now
from .audit import _audit


async def _get_active_binding(
    db: AsyncSession,
    *,
    secret_id: str,
    entity_type: str,
    entity_id: str,
) -> SecretScopeBinding | None:
    return (await db.execute(
        select(SecretScopeBinding).where(
            SecretScopeBinding.secret_id == secret_id,
            SecretScopeBinding.entity_type == entity_type,
            SecretScopeBinding.entity_id == entity_id,
            SecretScopeBinding.is_active.is_(True),
        )
    )).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Public API: Scope binding lifecycle
# ---------------------------------------------------------------------------


async def create_scope_binding(
    db: AsyncSession,
    *,
    secret_id: str,
    entity_type: str,
    entity_id: str,
    entity_label: str = "",
    permission: str = SCOPE_PERM_READ_ONLY,
    reason: str = "",
    created_by: str,
) -> SecretScopeBinding:
    """Create a new scope binding granting entity_id access to secret_id.

    Raises ValueError if entity_type is invalid or a binding already exists.
    """
    if entity_type not in SCOPE_ENTITY_TYPES:
        raise ValueError(
            f"Invalid entity_type '{entity_type}'. Must be one of: {sorted(SCOPE_ENTITY_TYPES)}"
        )
    secret = await db.get(StoredSecret, secret_id)
    if secret is None:
        raise ValueError(f"Secret '{secret_id}' not found")

    existing = await _get_active_binding(
        db, secret_id=secret_id, entity_type=entity_type, entity_id=entity_id
    )
    if existing:
        raise ValueError(
            f"Active binding already exists for entity {entity_type}/{entity_id} → secret {secret_id}"
        )

    binding = SecretScopeBinding(
        secret_id=secret_id,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label or entity_id,
        permission=permission,
        reason=reason,
        is_active=True,
        created_by=created_by,
    )
    db.add(binding)
    await db.flush()

    await _audit(
        db,
        secret_id=secret_id,
        action=AUDIT_ACTION_BIND,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user_id=created_by,
        outcome="success",
        context={"permission": permission, "binding_id": binding.id},
    )
    await db.flush()
    return binding


async def revoke_scope_binding(
    db: AsyncSession,
    *,
    binding_id: str,
    revoked_by: str,
    reason: str = "",
) -> SecretScopeBinding:
    """Revoke a scope binding (soft-delete: is_active=False)."""
    binding = await db.get(SecretScopeBinding, binding_id)
    if binding is None:
        raise ValueError(f"Binding '{binding_id}' not found")
    if not binding.is_active:
        raise ValueError(f"Binding '{binding_id}' is already revoked")

    binding.is_active = False
    binding.revoked_by = revoked_by
    binding.revoked_at = utc_now()
    await db.flush()

    await _audit(
        db,
        secret_id=binding.secret_id,
        action=AUDIT_ACTION_REVOKE,
        entity_type=binding.entity_type,
        entity_id=binding.entity_id,
        actor_user_id=revoked_by,
        outcome="success",
        context={"binding_id": binding_id, "reason": reason},
    )
    await db.flush()
    return binding


async def list_bindings_for_secret(
    db: AsyncSession,
    *,
    secret_id: str,
    active_only: bool = True,
) -> list[SecretScopeBinding]:
    """Return all (active) scope bindings for a given secret."""
    stmt = select(SecretScopeBinding).where(SecretScopeBinding.secret_id == secret_id)
    if active_only:
        stmt = stmt.where(SecretScopeBinding.is_active.is_(True))
    return list((await db.execute(stmt)).scalars().all())


async def list_bindings_for_entity(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    active_only: bool = True,
) -> list[SecretScopeBinding]:
    """Return all (active) scope bindings for a given entity."""
    stmt = select(SecretScopeBinding).where(
        SecretScopeBinding.entity_type == entity_type,
        SecretScopeBinding.entity_id == entity_id,
    )
    if active_only:
        stmt = stmt.where(SecretScopeBinding.is_active.is_(True))
    return list((await db.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# Public API: Scoped secret access
# ---------------------------------------------------------------------------


async def get_secret_value_for_entity(
    db: AsyncSession,
    *,
    secret_id: str,
    entity_type: str,
    entity_id: str,
    actor_user_id: str | None = None,
) -> str:
    """Return the decrypted secret value — only if entity has an active scope binding.

    Raises PermissionError if no active binding exists. Every call is audited.
    """
    binding = await _get_active_binding(
        db, secret_id=secret_id, entity_type=entity_type, entity_id=entity_id
    )
    if binding is None:
        await _audit(
            db,
            secret_id=secret_id,
            action=AUDIT_ACTION_READ,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_user_id=actor_user_id,
            outcome="denied",
            context={"reason": "no_active_binding"},
        )
        await db.flush()
        raise PermissionError(
            f"Entity {entity_type}/{entity_id} does not have an active scope binding for secret {secret_id}"
        )

    secret = await db.get(StoredSecret, secret_id)
    if secret is None:
        raise ValueError(f"Secret '{secret_id}' not found")

    value = decrypt_secret(secret.encrypted_value)

    await _audit(
        db,
        secret_id=secret_id,
        action=AUDIT_ACTION_READ,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        outcome="success",
        context={"binding_id": binding.id, "permission": binding.permission},
    )
    await db.flush()
    return value
