"""OIDC callback group mapping from validated ID tokens and rejected Entra group overage claims."""

import pytest
from sqlalchemy import select

import app.services.oidc.service as oidc_service_module
from app.models import IdentityGroup, IdentityProvider, Role, User, UserGroup, UserIdentity, UserRole


async def _seed_entra_provider_with_group_mappings(db) -> IdentityProvider:
    engineering_group = IdentityGroup(name="entra engineering", description="Engineering", is_active=True)
    db.add(engineering_group)
    await db.flush()
    provider = IdentityProvider(
        name="Entra SSO",
        provider_type="oidc",
        issuer_url="https://login.microsoftonline.com/tenant/v2.0",
        client_id="client-123",
        authorization_endpoint="https://login.microsoftonline.com/tenant/oauth2/v2.0/authorize",
        token_endpoint="https://login.microsoftonline.com/tenant/oauth2/v2.0/token",
        userinfo_endpoint="https://graph.microsoft.com/oidc/userinfo",
        jwks_uri="https://login.microsoftonline.com/tenant/discovery/v2.0/keys",
        scopes_json=["openid", "profile", "email"],
        group_role_mappings_json={"entra-group-id": ["admin"], "Octryx.Admin": ["admin"]},
        group_group_mappings_json={"entra-group-id": [engineering_group.id]},
        auto_provision_users=True,
        is_active=True,
    )
    db.add(provider)
    await db.commit()
    return provider


async def _fake_entra_discover(_provider):
    return {
        "issuer": "https://login.microsoftonline.com/tenant/v2.0",
        "authorization_endpoint": "https://login.microsoftonline.com/tenant/oauth2/v2.0/authorize",
        "token_endpoint": "https://login.microsoftonline.com/tenant/oauth2/v2.0/token",
        "userinfo_endpoint": "https://graph.microsoft.com/oidc/userinfo",
        "jwks_uri": "https://login.microsoftonline.com/tenant/discovery/v2.0/keys",
    }


async def _fake_entra_userinfo_claims(_userinfo_endpoint, _access_token):
    return {
        "sub": "entra-sub-123",
        "email": "entra-user@example.com",
        "preferred_username": "entra-user@example.com",
        "name": "Entra User",
    }


def _patch_oidc_service(monkeypatch, *, discover, exchange, fetch_userinfo, decode_id_token) -> None:
    monkeypatch.setattr(oidc_service_module, "_discover_provider_configuration", discover)
    monkeypatch.setattr(oidc_service_module, "_exchange_authorization_code", exchange)
    monkeypatch.setattr(oidc_service_module, "_fetch_userinfo_claims", fetch_userinfo)
    monkeypatch.setattr(oidc_service_module, "_decode_id_token_claims", decode_id_token)


async def _start_and_call_back(client, provider: IdentityProvider, code: str):
    start_resp = await client.get(
        f"/api/v1/auth/oidc/start/{provider.id}?target=/admin/chat",
        follow_redirects=False,
    )
    assert start_resp.status_code == 307
    state = start_resp.headers["location"].split("state=", 1)[1].split("&", 1)[0]

    return await client.get(
        f"/api/v1/auth/oidc/callback?state={state}&code={code}",
        follow_redirects=False,
    )


async def _assert_entra_user_identity_roles_and_groups(db, provider: IdentityProvider) -> None:
    user = (await db.execute(select(User).where(User.username == "entra-user-example-com"))).scalar_one()
    identity = (
        await db.execute(
            select(UserIdentity).where(
                UserIdentity.provider_id == provider.id,
                UserIdentity.user_id == user.id,
            )
        )
    ).scalar_one()
    assert identity.external_groups_json == ["Octryx.Admin", "entra-group-id"]
    assert identity.profile_json["groups"] == ["entra-group-id"]
    assert identity.profile_json["roles"] == ["Octryx.Admin"]

    roles = (
        await db.execute(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
        )
    ).scalars().all()
    assert "admin" in roles
    user_groups = (
        await db.execute(
            select(IdentityGroup.name)
            .join(UserGroup, UserGroup.group_id == IdentityGroup.id)
            .where(UserGroup.user_id == user.id)
        )
    ).scalars().all()
    assert "entra engineering" in user_groups


@pytest.mark.asyncio
async def test_oidc_callback_uses_validated_id_token_groups_for_mapping(client, db):
    provider = await _seed_entra_provider_with_group_mappings(db)

    async def fake_exchange_authorization_code(**kwargs):
        assert kwargs["code"] == "oidc-code-entra"
        return {
            "access_token": "access-token-entra",
            "refresh_token": "provider-refresh-entra",
            "id_token": "signed-id-token",
        }

    async def fake_decode_id_token_claims(**kwargs):
        assert kwargs["id_token"] == "signed-id-token"
        assert kwargs["provider"].id == provider.id
        assert kwargs["nonce"]
        return {
            "sub": "entra-sub-123",
            "email": "entra-user@example.com",
            "preferred_username": "entra-user@example.com",
            "name": "Entra User",
            "groups": ["entra-group-id"],
            "roles": ["Octryx.Admin"],
            "nonce": kwargs["nonce"],
        }

    monkeypatch = pytest.MonkeyPatch()
    _patch_oidc_service(
        monkeypatch,
        discover=_fake_entra_discover,
        exchange=fake_exchange_authorization_code,
        fetch_userinfo=_fake_entra_userinfo_claims,
        decode_id_token=fake_decode_id_token_claims,
    )
    try:
        callback_resp = await _start_and_call_back(client, provider, "oidc-code-entra")
        assert callback_resp.status_code == 303

        await _assert_entra_user_identity_roles_and_groups(db, provider)
    finally:
        monkeypatch.undo()


async def _fake_overage_discover(_provider):
    return {
        "authorization_endpoint": "https://login.microsoftonline.com/tenant/oauth2/v2.0/authorize",
        "token_endpoint": "https://login.microsoftonline.com/tenant/oauth2/v2.0/token",
        "userinfo_endpoint": "https://graph.microsoft.com/oidc/userinfo",
    }


async def _fake_overage_exchange_authorization_code(**kwargs):
    return {"access_token": "access-token-overage", "id_token": "signed-id-token-overage"}


async def _fake_overage_userinfo_claims(_userinfo_endpoint, _access_token):
    return {
        "sub": "entra-overage-sub",
        "email": "entra-overage@example.com",
        "preferred_username": "entra-overage@example.com",
        "name": "Entra Overage User",
    }


async def _fake_overage_id_token_claims(**kwargs):
    return {
        "sub": "entra-overage-sub",
        "_claim_names": {"groups": "src1"},
        "_claim_sources": {"src1": {"endpoint": "https://graph.windows.net/tenant/users/user/getMemberObjects"}},
        "nonce": kwargs["nonce"],
    }


@pytest.mark.asyncio
async def test_oidc_callback_rejects_entra_group_overage_claim(client, db):
    provider = IdentityProvider(
        name="Entra Overage SSO",
        provider_type="oidc",
        issuer_url="https://login.microsoftonline.com/tenant/v2.0",
        client_id="client-123",
        authorization_endpoint="https://login.microsoftonline.com/tenant/oauth2/v2.0/authorize",
        token_endpoint="https://login.microsoftonline.com/tenant/oauth2/v2.0/token",
        userinfo_endpoint="https://graph.microsoft.com/oidc/userinfo",
        scopes_json=["openid", "profile", "email"],
        auto_provision_users=True,
        is_active=True,
    )
    db.add(provider)
    await db.commit()

    monkeypatch = pytest.MonkeyPatch()
    _patch_oidc_service(
        monkeypatch,
        discover=_fake_overage_discover,
        exchange=_fake_overage_exchange_authorization_code,
        fetch_userinfo=_fake_overage_userinfo_claims,
        decode_id_token=_fake_overage_id_token_claims,
    )
    try:
        start_resp = await client.get(
            f"/api/v1/auth/oidc/start/{provider.id}?target=/admin/chat",
            follow_redirects=False,
        )
        assert start_resp.status_code == 307
        state = start_resp.headers["location"].split("state=", 1)[1].split("&", 1)[0]

        callback_resp = await client.get(
            f"/api/v1/auth/oidc/callback?state={state}&code=oidc-code-overage",
            follow_redirects=False,
        )
        assert callback_resp.status_code == 400
        assert "groups overage" in callback_resp.text
    finally:
        monkeypatch.undo()
