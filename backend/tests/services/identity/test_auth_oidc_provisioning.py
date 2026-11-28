"""OIDC callback user provisioning with refresh token rotation and the public provider list."""

import pytest
from sqlalchemy import select

import app.services.oidc.service as oidc_service_module
from app.models import IdentityGroup, IdentityProvider, RefreshToken, User, UserGroup, UserIdentity


async def _seed_example_provider(db) -> IdentityProvider:
    engineering_group = IdentityGroup(name="engineering", description="Engineering", is_active=True)
    db.add(engineering_group)
    await db.flush()
    provider = IdentityProvider(
        name="Example SSO",
        provider_type="oidc",
        issuer_url="https://issuer.example.com",
        client_id="client-123",
        authorization_endpoint="https://issuer.example.com/auth",
        token_endpoint="https://issuer.example.com/token",
        userinfo_endpoint="https://issuer.example.com/userinfo",
        scopes_json=["openid", "profile", "email", "groups"],
        group_role_mappings_json={"octryx-admins": ["admin"]},
        group_group_mappings_json={"octryx-admins": [engineering_group.id]},
        default_roles_json=["viewer"],
        default_group_ids_json=[engineering_group.id],
        auto_provision_users=True,
        is_active=True,
    )
    db.add(provider)
    await db.commit()
    return provider


async def _fake_discover(_provider):
    return {
        "authorization_endpoint": "https://issuer.example.com/auth",
        "token_endpoint": "https://issuer.example.com/token",
        "userinfo_endpoint": "https://issuer.example.com/userinfo",
    }


async def _fake_exchange_authorization_code(**kwargs):
    assert kwargs["code"] == "oidc-code-1"
    return {
        "access_token": "access-token-1",
        "refresh_token": "provider-refresh-1",
    }


async def _fake_fetch_userinfo_claims(_userinfo_endpoint, _access_token):
    return {
        "sub": "user-sub-123",
        "email": "oidc-user@example.com",
        "preferred_username": "oidc-user",
        "name": "OIDC User",
        "groups": ["octryx-admins"],
    }


async def _assert_provisioned_identity_and_groups(db, provider: IdentityProvider) -> None:
    user = (await db.execute(select(User).where(User.username == "oidc-user"))).scalar_one()
    assert user.auth_source == "oidc"
    identity = (
        await db.execute(
            select(UserIdentity).where(
                UserIdentity.provider_id == provider.id,
                UserIdentity.user_id == user.id,
            )
        )
    ).scalar_one()
    assert identity.subject == "user-sub-123"
    assert "octryx-admins" in (identity.external_groups_json or [])
    user_groups = (
        await db.execute(
            select(IdentityGroup.name)
            .join(UserGroup, UserGroup.group_id == IdentityGroup.id)
            .where(UserGroup.user_id == user.id)
        )
    ).scalars().all()
    assert "engineering" in user_groups

    refresh_rows = (await db.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))).scalars().all()
    assert refresh_rows


@pytest.mark.asyncio
async def test_oidc_callback_auto_provisions_user_and_rotates_refresh_token(client, db):
    provider = await _seed_example_provider(db)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(oidc_service_module, "_discover_provider_configuration", _fake_discover)
    monkeypatch.setattr(oidc_service_module, "_exchange_authorization_code", _fake_exchange_authorization_code)
    monkeypatch.setattr(oidc_service_module, "_fetch_userinfo_claims", _fake_fetch_userinfo_claims)
    try:
        start_resp = await client.get(
            f"/api/v1/auth/oidc/start/{provider.id}?target=/admin/chat",
            follow_redirects=False,
        )
        assert start_resp.status_code == 307
        location = start_resp.headers["location"]
        assert "state=" in location
        state = location.split("state=", 1)[1].split("&", 1)[0]

        callback_resp = await client.get(
            f"/api/v1/auth/oidc/callback?state={state}&code=oidc-code-1",
            follow_redirects=False,
        )
        assert callback_resp.status_code == 303
        assert callback_resp.headers["location"] == "/admin/chat"
        set_cookie = "\n".join(callback_resp.headers.get_list("set-cookie"))
        assert "access_token=" in set_cookie
        assert "refresh_token=" in set_cookie

        await _assert_provisioned_identity_and_groups(db, provider)

        refresh_token_cookie = None
        for raw_header in callback_resp.headers.get_list("set-cookie"):
            if raw_header.startswith("refresh_token="):
                refresh_token_cookie = raw_header.split(";", 1)[0].split("=", 1)[1]
        assert refresh_token_cookie

        refresh_resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token_cookie})
        assert refresh_resp.status_code == 200
        payload = refresh_resp.json()
        assert payload["access_token"]
        assert payload["refresh_token"]
        assert payload["refresh_token"] != refresh_token_cookie
    finally:
        monkeypatch.undo()


@pytest.mark.asyncio
async def test_public_oidc_provider_list_shows_active_providers(client, db):
    db.add(
        IdentityProvider(
            name="Azure Entra",
            provider_type="oidc",
            issuer_url="https://login.microsoftonline.com/tenant/v2.0",
            client_id="entra-client",
            authorization_endpoint="https://login.microsoftonline.com/tenant/oauth2/v2.0/authorize",
            token_endpoint="https://login.microsoftonline.com/tenant/oauth2/v2.0/token",
            userinfo_endpoint="https://graph.microsoft.com/oidc/userinfo",
            is_active=True,
        )
    )
    await db.commit()

    resp = await client.get("/api/v1/auth/oidc/providers")
    assert resp.status_code == 200
    payload = resp.json()
    assert any(item["name"] == "Azure Entra" for item in payload)
