"""Identity provider views: the admin API shape and the audit snapshot."""

from __future__ import annotations

from typing import Any

from ...models import IdentityProvider


def _identity_provider_audit_snapshot(provider: IdentityProvider | None) -> dict[str, Any]:
    if provider is None:
        return {}
    return {
        "id": provider.id,
        "name": provider.name,
        "provider_type": provider.provider_type,
        "issuer_url": provider.issuer_url,
        "discovery_url": provider.discovery_url,
        "authorization_endpoint": provider.authorization_endpoint,
        "token_endpoint": provider.token_endpoint,
        "userinfo_endpoint": provider.userinfo_endpoint,
        "jwks_uri": provider.jwks_uri,
        "client_id": provider.client_id,
        "clientAuthConfigured": bool(provider.client_secret_secret_ref),
        "scopes": list(provider.scopes_json or []),
        "claim_mappings": provider.claim_mappings_json if isinstance(provider.claim_mappings_json, dict) else {},
        "group_role_mappings": (
            provider.group_role_mappings_json if isinstance(provider.group_role_mappings_json, dict) else {}
        ),
        "group_group_mappings": (
            provider.group_group_mappings_json if isinstance(provider.group_group_mappings_json, dict) else {}
        ),
        "default_roles": list(provider.default_roles_json or []),
        "default_group_ids": list(provider.default_group_ids_json or []),
        "auto_provision_users": provider.auto_provision_users,
        "is_active": provider.is_active,
    }


def serialize_identity_provider(provider: IdentityProvider) -> dict[str, Any]:
    return {
        "id": provider.id,
        "name": provider.name or "",
        "providerType": provider.provider_type or "",
        "issuerUrl": provider.issuer_url or "",
        "discoveryUrl": provider.discovery_url or "",
        "authorizationEndpoint": provider.authorization_endpoint or "",
        "tokenEndpoint": provider.token_endpoint or "",
        "userinfoEndpoint": provider.userinfo_endpoint or "",
        "jwksUri": provider.jwks_uri or "",
        "clientId": provider.client_id or "",
        "scopes": list(provider.scopes_json or []),
        "claimMappings": provider.claim_mappings_json if isinstance(provider.claim_mappings_json, dict) else {},
        "groupRoleMappings": (
            provider.group_role_mappings_json if isinstance(provider.group_role_mappings_json, dict) else {}
        ),
        "groupGroupMappings": (
            provider.group_group_mappings_json if isinstance(provider.group_group_mappings_json, dict) else {}
        ),
        "defaultRoles": list(provider.default_roles_json or []),
        "defaultGroupIds": list(provider.default_group_ids_json or []),
        "autoProvisionUsers": bool(provider.auto_provision_users),
        "isActive": bool(provider.is_active),
        "createdAt": provider.created_at.isoformat() if provider.created_at else None,
        "updatedAt": provider.updated_at.isoformat() if provider.updated_at else None,
    }
