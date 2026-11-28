"""OIDC claim extraction and provider mapping helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException

from ..models import IdentityProvider


@dataclass(frozen=True)
class OidcResolvedClaims:
    subject: str
    external_email: str | None
    external_username: str | None
    display_name: str
    external_groups: list[str]
    # The groups claim and the roles claim apart (work-role assignments by SSO group / SSO role).
    sso_groups: list[str] = field(default_factory=list)
    sso_roles: list[str] = field(default_factory=list)


def claim_mapping(provider: IdentityProvider) -> dict[str, str]:
    raw = provider.claim_mappings_json if isinstance(provider.claim_mappings_json, dict) else {}
    return {
        "subject": str(raw.get("subject") or "sub"),
        "email": str(raw.get("email") or "email"),
        "username": str(raw.get("username") or "preferred_username"),
        "display_name": str(raw.get("display_name") or "name"),
        "groups": str(raw.get("groups") or "groups"),
        "roles": str(raw.get("roles") or "roles"),
    }


def group_role_mappings(provider: IdentityProvider) -> dict[str, list[str]]:
    raw = provider.group_role_mappings_json if isinstance(provider.group_role_mappings_json, dict) else {}
    normalized: dict[str, list[str]] = {}
    for key, value in raw.items():
        group_name = str(key or "").strip()
        if not group_name:
            continue
        if isinstance(value, list):
            roles = [str(item).strip() for item in value if str(item).strip()]
        else:
            roles = [str(value).strip()] if str(value or "").strip() else []
        if roles:
            normalized[group_name] = roles
    return normalized


def group_group_mappings(provider: IdentityProvider) -> dict[str, list[str]]:
    raw = provider.group_group_mappings_json if isinstance(provider.group_group_mappings_json, dict) else {}
    normalized: dict[str, list[str]] = {}
    for key, value in raw.items():
        group_name = str(key or "").strip()
        if not group_name:
            continue
        if isinstance(value, list):
            local_groups = [str(item).strip() for item in value if str(item).strip()]
        else:
            local_groups = [str(value).strip()] if str(value or "").strip() else []
        if local_groups:
            normalized[group_name] = local_groups
    return normalized


def default_role_names(provider: IdentityProvider) -> list[str]:
    raw = provider.default_roles_json if isinstance(provider.default_roles_json, list) else []
    return [str(item).strip() for item in raw if str(item).strip()]


def default_group_ids(provider: IdentityProvider) -> list[str]:
    raw = provider.default_group_ids_json if isinstance(provider.default_group_ids_json, list) else []
    return [str(item).strip() for item in raw if str(item).strip()]


def claim_value(claims: dict[str, Any], key: str) -> Any:
    if "." not in key:
        return claims.get(key)
    current: Any = claims
    for part in key.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def merge_oidc_claims(userinfo_claims: dict[str, Any], id_token_claims: dict[str, Any]) -> dict[str, Any]:
    # Token security claims from the validated ID token are preserved.
    if not id_token_claims:
        return dict(userinfo_claims or {})
    merged = dict(id_token_claims)
    security_claims = {
        "_claim_names",
        "_claim_sources",
        "aud",
        "exp",
        "groups",
        "hasgroups",
        "iat",
        "iss",
        "nbf",
        "nonce",
        "oid",
        "roles",
        "sub",
        "tid",
        "wids",
    }
    for key, value in (userinfo_claims or {}).items():
        if key in security_claims and key in merged:
            continue
        merged[key] = value
    return merged


def _list_claim(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def resolve_identity_claims(provider: IdentityProvider, claims: dict[str, Any]) -> OidcResolvedClaims:
    mapping = claim_mapping(provider)
    subject = str(claim_value(claims, mapping["subject"]) or "").strip()
    if not subject:
        raise HTTPException(status_code=400, detail="OIDC claims missing subject")

    claim_names = claims.get("_claim_names")
    if isinstance(claim_names, dict) and "groups" in claim_names:
        raise HTTPException(
            status_code=400,
            detail=(
                "OIDC groups overage claim received. Configure the Entra app to emit only groups assigned to the "
                "application or add an explicit Microsoft Graph group lookup flow."
            ),
        )
    if claims.get("hasgroups") is True:
        raise HTTPException(
            status_code=400,
            detail=(
                "OIDC groups overage claim received. Configure the Entra app to emit only groups assigned to the "
                "application or add an explicit Microsoft Graph group lookup flow."
            ),
        )

    sso_groups, sso_roles = sso_claim_lists(claims, mapping)
    external_groups = [*sso_groups, *sso_roles]

    return OidcResolvedClaims(
        subject=subject,
        external_email=str(claim_value(claims, mapping["email"]) or "").strip() or None,
        external_username=str(claim_value(claims, mapping["username"]) or "").strip() or None,
        display_name=str(claim_value(claims, mapping["display_name"]) or "").strip(),
        external_groups=sorted({group for group in external_groups if group}),
        sso_groups=sso_groups,
        sso_roles=sso_roles,
    )


def sso_claim_lists(claims: dict[str, Any], mapping: dict[str, str]) -> tuple[list[str], list[str]]:
    groups = sorted(set(_list_claim(claim_value(claims, mapping["groups"]))))
    roles = sorted(set(_list_claim(claim_value(claims, mapping["roles"]))))
    return groups, roles
