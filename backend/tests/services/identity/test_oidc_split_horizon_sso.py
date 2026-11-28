"""Single sign-on with a split-horizon provider such as IdP."""

from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.config import get_settings
from app.models import Role, User, UserRole
from app.models.security.identity import IdentityProvider
from app.services.auth import hash_password
from app.services.oidc import provider_http, provisioning

MAPPINGS = {"ADMIN": ["admin"], "ANALYST": ["operator"], "VIEWER": ["viewer"]}


def _provider(**extra) -> IdentityProvider:
    fields = dict(
        id=str(uuid.uuid4()),
        name="IdP",
        provider_type="oidc",
        issuer_url="http://idp:8080",
        authorization_endpoint="https://idp.example.test/oauth2/authorize",
        token_endpoint="http://idp.gateway.svc:8080/oauth2/token",
        userinfo_endpoint="http://idp.gateway.svc:8080/oauth2/userinfo",
        jwks_uri="http://idp.gateway.svc:8080/.well-known/jwks.json",
        client_id="octryx",
        scopes_json=["openid", "profile", "email"],
        group_role_mappings_json=MAPPINGS,
        default_roles_json=[],
        is_active=True,
    )
    return IdentityProvider(**{**fields, **extra})


@pytest.mark.asyncio
async def test_explicit_endpoints_need_no_discovery(monkeypatch):
    def no_network(*_args, **_kwargs):
        raise AssertionError("discovery must not be requested")

    monkeypatch.setattr(provider_http.httpx, "AsyncClient", no_network)
    assert await provider_http._discover_provider_configuration(_provider()) == {}


async def _user(db) -> User:
    user = User(id=str(uuid.uuid4()), username=f"idp-{uuid.uuid4().hex[:6]}", email=f"{uuid.uuid4().hex[:6]}@x.test",
                password_hash=hash_password("x" * 20), auth_source="oidc", account_type="human", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def _roles(db, user: User) -> set[str]:
    rows = await db.execute(select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user.id))
    return {row[0] for row in rows.all()}


@pytest.mark.asyncio
async def test_roles_follow_the_providers_groups_and_hand_granted_roles_stay(db):
    provider = _provider()
    user = await _user(db)
    technical = (await db.execute(select(Role).where(Role.name == "technical"))).scalar_one()
    db.add(UserRole(user_id=user.id, role_id=technical.id))  # granted by hand, never mapped
    await db.flush()

    await provisioning._apply_group_role_mapping(db, user=user, provider=provider, external_groups=["ADMIN", "TENANT_7"])
    await db.flush()
    assert await _roles(db, user) == {"admin", "technical"}

    await provisioning._apply_group_role_mapping(db, user=user, provider=provider, external_groups=["ANALYST"])
    await db.flush()
    assert await _roles(db, user) == {"operator", "technical"}


@pytest.mark.asyncio
async def test_no_mapped_group_and_no_default_role_is_refused(db):
    user = await _user(db)
    with pytest.raises(HTTPException) as refused:
        await provisioning._apply_group_role_mapping(db, user=user, provider=_provider(), external_groups=["TENANT_7"])
    assert refused.value.status_code == 403
    granted = await provisioning._apply_group_role_mapping(
        db, user=user, provider=_provider(default_roles_json=["viewer"]), external_groups=["TENANT_7"]
    )
    assert granted == ["viewer"]


@pytest.mark.asyncio
async def test_the_redirect_uri_is_the_public_https_callback(client, db, monkeypatch):
    provider = _provider()
    db.add(provider)
    await db.commit()
    monkeypatch.setattr(get_settings(), "platform_public_origin", "https://octryx.example.test")

    response = await client.get(f"/api/v1/auth/oidc/start/{provider.id}", follow_redirects=False)

    assert response.status_code == 307
    location = urlparse(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == "https://idp.example.test/oauth2/authorize"
    query = parse_qs(location.query)
    assert query["redirect_uri"] == ["https://octryx.example.test/api/v1/auth/oidc/callback"]
    assert query["client_id"] == ["octryx"]
