"""Users from OIDC sign-ins: find or provision the account, record the login, map groups to roles and groups."""

from __future__ import annotations

import secrets
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import IdentityGroup, IdentityProvider, Role, User, UserGroup, UserIdentity, UserRole
from ...time_utils import utc_now
from ..auth import hash_password, user_has_permission
from ..oidc_claims import default_group_ids, default_role_names, group_group_mappings, group_role_mappings
from ..secret import encrypt_secret


def _safe_username(base: str) -> str:
    sanitized = "".join(ch.lower() if ch.isalnum() else "-" for ch in base).strip("-")
    return sanitized[:80] or f"user-{uuid.uuid4().hex[:8]}"


async def _allocate_username(db: AsyncSession, preferred: str) -> str:
    base = _safe_username(preferred)
    candidate = base
    suffix = 1
    while True:
        existing = (await db.execute(select(User).where(User.username == candidate))).scalar_one_or_none()
        if not existing:
            return candidate
        suffix += 1
        candidate = f"{base[:70]}-{suffix}"


async def _role_by_name(db: AsyncSession, name: str) -> Role | None:
    return (await db.execute(select(Role).where(Role.name == name))).scalar_one_or_none()


async def _apply_group_role_mapping(
    db: AsyncSession,
    *,
    user: User,
    provider: IdentityProvider,
    external_groups: list[str],
) -> list[str]:
    role_names: set[str] = set()
    mappings = group_role_mappings(provider)
    defaults = default_role_names(provider)
    for group in external_groups:
        role_names.update(mappings.get(str(group), []))
    if mappings and not defaults and not role_names:
        # The provider maps groups and grants nothing by default: no mapped group means no access.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Login is not permitted for this user")
    role_names.update(defaults)
    if not role_names:
        role_names.add("viewer")
    # Roles this provider grants are kept in step with its groups: a role the provider no longer grants is
    # removed. Roles the provider never maps (granted by hand) stay.
    managed = {role for roles in mappings.values() for role in roles} | set(defaults)
    revoked = sorted(managed - role_names)
    if revoked:
        await db.execute(
            delete(UserRole).where(
                UserRole.user_id == user.id,
                UserRole.role_id.in_(select(Role.id).where(Role.name.in_(revoked))),
            )
        )
    existing_roles = {
        row[0]
        for row in (
            await db.execute(
                select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user.id)
            )
        ).all()
    }
    for role_name in sorted(role_names):
        if role_name in existing_roles:
            continue
        role = await _role_by_name(db, role_name)
        if role:
            db.add(UserRole(user_id=user.id, role_id=role.id))
    return sorted(role_names)


async def _apply_group_group_mapping(
    db: AsyncSession,
    *,
    user: User,
    provider: IdentityProvider,
    external_groups: list[str],
) -> list[str]:
    group_ids: set[str] = set(default_group_ids(provider))
    mappings = group_group_mappings(provider)
    for group in external_groups:
        group_ids.update(mappings.get(str(group), []))
    if not group_ids:
        return []

    existing_group_ids = {
        row[0] for row in (await db.execute(select(UserGroup.group_id).where(UserGroup.user_id == user.id))).all()
    }
    valid_groups = (
        await db.execute(select(IdentityGroup).where(IdentityGroup.id.in_(sorted(group_ids)), IdentityGroup.is_active))
    ).scalars().all()
    for group in valid_groups:
        if group.id not in existing_group_ids:
            db.add(UserGroup(user_id=user.id, group_id=group.id))
    return sorted(group.name for group in valid_groups)


async def _find_or_provision_user(
    db: AsyncSession,
    *,
    provider: IdentityProvider,
    resolved_claims: Any,
) -> tuple[User, UserIdentity]:
    """The user linked to the provider's subject; without one, a new user and identity when the provider
    provisions users automatically (403 otherwise)."""
    identity = (
        await db.execute(
            select(UserIdentity).where(
                UserIdentity.provider_id == provider.id,
                UserIdentity.subject == resolved_claims.subject,
            )
        )
    ).scalar_one_or_none()

    if identity:
        user = await db.get(User, identity.user_id)
    else:
        user = None
    if not user:
        if not provider.auto_provision_users:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Auto provisioning is disabled")
        username_source = resolved_claims.external_username or (
            resolved_claims.external_email or resolved_claims.subject
        )
        username = await _allocate_username(db, username_source)
        email = resolved_claims.external_email or f"{username}@{provider.name.lower().replace(' ', '-')}.local"
        user = User(
            id=str(uuid.uuid4()),
            username=username,
            email=email,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            display_name=resolved_claims.display_name or username,
            auth_source="oidc",
            account_type="human",
            is_active=True,
        )
        db.add(user)
        await db.flush()
        identity = UserIdentity(
            id=str(uuid.uuid4()),
            user_id=user.id,
            provider_id=provider.id,
            subject=resolved_claims.subject,
        )
        db.add(identity)
    return user, identity


def _record_identity_login(
    *,
    identity: UserIdentity,
    user: User,
    resolved_claims: Any,
    claims: dict[str, Any],
    access_token: str,
    raw_id_token: str,
) -> None:
    identity.external_email = resolved_claims.external_email
    identity.external_username = resolved_claims.external_username
    identity.external_groups_json = resolved_claims.external_groups
    identity.sso_groups_json = resolved_claims.sso_groups
    identity.sso_roles_json = resolved_claims.sso_roles
    identity.encrypted_access_token = encrypt_secret(access_token)
    if raw_id_token:
        identity.encrypted_id_token = encrypt_secret(raw_id_token)
    identity.profile_json = claims
    identity.last_login_at = utc_now()

    user.display_name = resolved_claims.display_name or user.display_name or user.username
    if resolved_claims.external_email and not user.email:
        user.email = resolved_claims.external_email
    user.auth_source = "oidc"


async def _apply_access_mappings(
    db: AsyncSession,
    *,
    user: User,
    provider: IdentityProvider,
    external_groups: list[str],
) -> tuple[list[str], list[str]]:
    """Grant the mapped roles and groups, then refuse the sign-in when the user may not log in."""
    assigned_roles = await _apply_group_role_mapping(
        db,
        user=user,
        provider=provider,
        external_groups=external_groups,
    )
    assigned_groups = await _apply_group_group_mapping(
        db,
        user=user,
        provider=provider,
        external_groups=external_groups,
    )
    if not await user_has_permission(db, user.id, resource="auth", action="login"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Login is not permitted for this user")
    return assigned_roles, assigned_groups
