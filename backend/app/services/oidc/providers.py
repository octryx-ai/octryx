"""Identity provider administration: list, validate and save providers."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import IdentityGroup, IdentityProvider, Role
from ..admin.governance.admin_config_audit_service import record_admin_config_audit
from ..oidc_claims import (
    default_group_ids,
    default_role_names,
    group_group_mappings,
    group_role_mappings,
)
from ..secret import set_secret_value
from .serialization import _identity_provider_audit_snapshot

DEFAULT_SCOPE = ["openid", "profile", "email"]


async def list_identity_providers(
    db: AsyncSession,
    *,
    active_only: bool = False,
) -> list[IdentityProvider]:
    stmt = select(IdentityProvider).order_by(IdentityProvider.is_active.desc(), IdentityProvider.name.asc())
    if active_only:
        stmt = stmt.where(IdentityProvider.is_active)
    return (await db.execute(stmt)).scalars().all()


async def list_public_oidc_providers(db: AsyncSession) -> list[dict[str, Any]]:
    providers = await list_identity_providers(db, active_only=True)
    return [
        {
            "id": provider.id,
            "name": provider.name,
            "providerType": provider.provider_type,
        }
        for provider in providers
        if (provider.provider_type or "").lower() == "oidc"
    ]


def _normalize_string_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail=f"{field_name} must be a list")
    return sorted({str(item).strip() for item in value if str(item).strip()})


def _normalize_external_group_mapping(value: Any, *, field_name: str) -> dict[str, list[str]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail=f"{field_name} must be an object")
    normalized: dict[str, list[str]] = {}
    for raw_group, raw_targets in value.items():
        external_group = str(raw_group or "").strip()
        if not external_group:
            continue
        if isinstance(raw_targets, list):
            targets = [str(item).strip() for item in raw_targets if str(item).strip()]
        else:
            targets = [str(raw_targets).strip()] if str(raw_targets or "").strip() else []
        if targets:
            normalized[external_group] = sorted(set(targets))
    return normalized


async def _validate_role_names(db: AsyncSession, role_names: list[str]) -> None:
    normalized = sorted({name for name in role_names if name})
    if not normalized:
        return
    rows = await db.execute(select(Role.name).where(Role.name.in_(normalized)))
    found = {row[0] for row in rows.all()}
    missing = sorted(set(normalized) - found)
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown role(s): {', '.join(missing)}")


async def _validate_group_ids(db: AsyncSession, group_ids: list[str]) -> None:
    normalized = sorted({group_id for group_id in group_ids if group_id})
    if not normalized:
        return
    rows = await db.execute(select(IdentityGroup.id).where(IdentityGroup.id.in_(normalized)))
    found = {row[0] for row in rows.all()}
    missing = sorted(set(normalized) - found)
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown group id(s): {', '.join(missing)}")


async def _load_or_create_provider(
    db: AsyncSession,
    payload: dict[str, Any],
) -> tuple[IdentityProvider, dict[str, Any] | None]:
    provider_id = str(payload.get("id") or "").strip()
    if provider_id:
        stmt = select(IdentityProvider).where(IdentityProvider.id == provider_id)
        provider = (await db.execute(stmt)).scalar_one_or_none()
        if not provider:
            raise HTTPException(status_code=404, detail="Identity provider not found")
        return provider, _identity_provider_audit_snapshot(provider)
    provider = IdentityProvider(id=str(uuid.uuid4()))
    db.add(provider)
    return provider, None


def _apply_provider_endpoints(provider: IdentityProvider, payload: dict[str, Any]) -> None:
    name = str(payload.get("name") or provider.name or "").strip()
    provider_type = str(payload.get("provider_type") or provider.provider_type or "oidc").strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if provider_type not in {"oidc", "oauth2", "saml", "azure_ad", "google", "github"}:
        raise HTTPException(status_code=400, detail="Unsupported provider_type")

    provider.name = name
    provider.provider_type = provider_type
    provider.issuer_url = str(payload.get("issuer_url") or provider.issuer_url or "").strip() or None
    provider.discovery_url = str(payload.get("discovery_url") or provider.discovery_url or "").strip() or None
    provider.authorization_endpoint = (
        str(payload.get("authorization_endpoint") or provider.authorization_endpoint or "").strip() or None
    )
    provider.token_endpoint = str(payload.get("token_endpoint") or provider.token_endpoint or "").strip() or None
    provider.userinfo_endpoint = (
        str(payload.get("userinfo_endpoint") or provider.userinfo_endpoint or "").strip() or None
    )
    provider.jwks_uri = str(payload.get("jwks_uri") or provider.jwks_uri or "").strip() or None
    provider.client_id = str(payload.get("client_id") or provider.client_id or "").strip() or None
    provider.scopes_json = [
        str(item).strip()
        for item in (payload.get("scopes") or provider.scopes_json or DEFAULT_SCOPE)
        if str(item).strip()
    ]


async def _apply_provider_mappings(db: AsyncSession, provider: IdentityProvider, payload: dict[str, Any]) -> None:
    claim_mappings = payload.get("claim_mappings") if "claim_mappings" in payload else provider.claim_mappings_json
    group_role_mapping = (
        _normalize_external_group_mapping(payload.get("group_role_mappings"), field_name="group_role_mappings")
        if "group_role_mappings" in payload
        else group_role_mappings(provider)
    )
    group_group_mapping = (
        _normalize_external_group_mapping(payload.get("group_group_mappings"), field_name="group_group_mappings")
        if "group_group_mappings" in payload
        else group_group_mappings(provider)
    )
    default_roles = (
        _normalize_string_list(payload.get("default_roles"), field_name="default_roles")
        if "default_roles" in payload
        else default_role_names(provider)
    )
    default_groups = (
        _normalize_string_list(payload.get("default_group_ids"), field_name="default_group_ids")
        if "default_group_ids" in payload
        else default_group_ids(provider)
    )
    await _validate_role_names(
        db,
        [role for roles in group_role_mapping.values() for role in roles] + default_roles,
    )
    await _validate_group_ids(
        db,
        [group_id for group_ids in group_group_mapping.values() for group_id in group_ids] + default_groups,
    )
    provider.claim_mappings_json = claim_mappings if isinstance(claim_mappings, dict) else {}
    provider.group_role_mappings_json = group_role_mapping
    provider.group_group_mappings_json = group_group_mapping
    provider.default_roles_json = default_roles
    provider.default_group_ids_json = default_groups


async def upsert_identity_provider(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    serialize_provider: Callable[[IdentityProvider], dict[str, Any]],
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    provider, before_audit = await _load_or_create_provider(db, payload)
    _apply_provider_endpoints(provider, payload)
    await _apply_provider_mappings(db, provider, payload)
    provider.auto_provision_users = bool(payload.get("auto_provision_users", provider.auto_provision_users))
    provider.is_active = bool(payload.get("is_active", provider.is_active))

    client_secret = str(payload.get("client_secret") or "").strip()
    if client_secret:
        secret_entry = await set_secret_value(
            db,
            tool_name=f"identity_provider:{provider.id}",
            field_name="client_secret",
            project_id=None,
            value=client_secret,
        )
        provider.client_secret_secret_ref = secret_entry.id

    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.security.identity_provider.saved",
        resource_type="identity_provider",
        resource_id=provider.id,
        project_id=None,
        before=before_audit,
        after=_identity_provider_audit_snapshot(provider),
        details={
            "operation": "upsert_identity_provider",
            "payload_keys": sorted(str(key) for key in payload),
        },
    )
    await db.commit()
    await db.refresh(provider)
    return serialize_provider(provider)
