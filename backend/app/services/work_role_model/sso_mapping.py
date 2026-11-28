"""SSO mapping per identity provider: which claim carries the groups and which the roles."""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import IdentityProvider, User, UserIdentity
from . import audit
from .errors import WorkRoleError, require_platform_admin

_CLAIM = re.compile(r"^[A-Za-z0-9_:\-/]+(?:\.[A-Za-z0-9_:\-/]+)*$")
DEFAULT_GROUPS, DEFAULT_ROLES = "groups", "roles"


def claims_of(provider: IdentityProvider) -> tuple[str, str]:
    raw = provider.claim_mappings_json if isinstance(provider.claim_mappings_json, dict) else {}
    return str(raw.get("groups") or DEFAULT_GROUPS), str(raw.get("roles") or DEFAULT_ROLES)


def _values(raw: object) -> list[str]:
    return [str(item) for item in raw if str(item).strip()] if isinstance(raw, list) else []


async def _known(db: AsyncSession, provider_id: str) -> tuple[list[str], list[str]]:
    groups: set[str] = set()
    roles: set[str] = set()
    rows = (await db.execute(select(UserIdentity.sso_groups_json, UserIdentity.sso_roles_json).where(
        UserIdentity.provider_id == provider_id))).all()
    for found_groups, found_roles in rows:
        groups.update(_values(found_groups))
        roles.update(_values(found_roles))
    return sorted(groups), sorted(roles)


async def _view(db: AsyncSession, provider: IdentityProvider) -> dict[str, Any]:
    groups_claim, roles_claim = claims_of(provider)
    known_groups, known_roles = await _known(db, provider.id)
    return {"id": provider.id, "name": provider.name, "groups_claim": groups_claim, "roles_claim": roles_claim,
            "known_groups": known_groups, "known_roles": known_roles}


async def list_mappings(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    await require_platform_admin(db, user, "the SSO mapping")
    providers = (await db.execute(select(IdentityProvider).order_by(IdentityProvider.name))).scalars().all()
    return [await _view(db, provider) for provider in providers]


async def set_mapping(db: AsyncSession, user: User, provider_id: str, body: dict[str, Any]) -> dict[str, Any]:
    await require_platform_admin(db, user, "the SSO mapping")
    provider = await db.get(IdentityProvider, provider_id)
    if provider is None:
        raise WorkRoleError("unknown_provider", "Unknown identity provider.", 404)
    wanted = {}
    for key in ("groups_claim", "roles_claim"):
        value = str(body.get(key) or "").strip()
        if not _CLAIM.match(value):
            raise WorkRoleError("invalid_claim", f"{key} is a claim name or a dotted path.", 422, field=key)
        wanted[key] = value
    before = dict(zip(("groups_claim", "roles_claim"), claims_of(provider), strict=True))
    mapping = dict(provider.claim_mappings_json or {}) if isinstance(provider.claim_mappings_json, dict) else {}
    mapping.update(groups=wanted["groups_claim"], roles=wanted["roles_claim"])
    provider.claim_mappings_json = mapping
    if before != wanted:
        audit.record(db, actor_id=user.id, action="sso_mapping.changed", target_type="identity_provider",
                     target_id=provider.id, label=provider.name, before=before, after=wanted)
    await db.flush()
    return await _view(db, provider)


async def my_claims(db: AsyncSession, user: User, provider_id: str) -> dict[str, Any]:
    identity = (await db.execute(select(UserIdentity).where(UserIdentity.user_id == user.id,
                                                            UserIdentity.provider_id == provider_id))
                ).scalar_one_or_none()
    if identity is None:
        return {"groups": [], "roles": [], "signed_in_at": None}
    provider = await db.get(IdentityProvider, provider_id)
    groups, roles = _values(identity.sso_groups_json), _values(identity.sso_roles_json)
    if provider is not None and isinstance(identity.profile_json, dict) and identity.profile_json:
        # The claims of that sign-in read with the mapping as it is now: the admin tests an edit before anyone
        # signs in again.
        from ..oidc_claims import claim_mapping, sso_claim_lists

        groups, roles = sso_claim_lists(identity.profile_json, claim_mapping(provider))
    return {"groups": groups, "roles": roles,
            "signed_in_at": identity.last_login_at.isoformat() if identity.last_login_at else None}


__all__ = ["claims_of", "list_mappings", "my_claims", "set_mapping"]
