"""D1 device credential: a device grant needs no web session, has its own lifetime and dies with the
device, a password change or the user's deactivation."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models.security.device import DEVICE_STATUS_REVOKED
from app.models.security.oauth_provider import OAuthGrant
from app.services.agent_gateway.contract import GATEWAY_AUDIENCE
from app.services.devices.contract import DEVICE_AUDIENCE
from app.services.devices.credential import (
    DeviceCredential,
    device_grant_scopes,
    resolve_device_credential,
    revoke_device_grant,
    revoke_user_device_grants,
)
from app.services.oauth_provider.tokens import mint_access_token
from app.time_utils import utc_now
from tests.devices.device_support import device_with_grant, oauth_client, user_named
from tests.support.oauth_test_utils import obtain_oauth_tokens


async def _refresh(client, refresh_token: str, resource: str):
    return await client.post("/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": "octryx-test-client",
        "resource": resource,
    })


def test_device_grant_scopes_never_exceed_the_login():
    assert device_grant_scopes(["model:invoke", "knowledge:write", "work:manage"]) == ["device:connect",
                                                                                         "knowledge:write",
                                                                                         "model:invoke"]
    assert device_grant_scopes([]) == ["device:connect"]


@pytest.mark.asyncio
async def test_device_grant_refreshes_without_a_web_session_and_mints_short_channel_tokens(client, db):
    user = await user_named(db, "device-owner")
    device, refresh = await device_with_grant(db, user)

    response = await _refresh(client, refresh, DEVICE_AUDIENCE)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["expires_in"] == 15 * 60
    assert set(body["scope"].split()) == {"device:connect", "model:invoke", "knowledge:read", "knowledge:write"}
    resolved = await resolve_device_credential(db, body["access_token"])
    assert isinstance(resolved, DeviceCredential)
    assert resolved.device.id == device.id and resolved.user_id == user.id

    # The rotated token serves the gateway audience too (the job's apiKeyHelper).
    gateway = await _refresh(client, body["refresh_token"], GATEWAY_AUDIENCE)
    assert gateway.status_code == 200, gateway.text


@pytest.mark.asyncio
async def test_a_login_grant_never_gets_the_device_audience(client, db):
    tokens = await obtain_oauth_tokens(client, scope="model:invoke")
    response = await client.post("/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": tokens["client_id"],
        "resource": DEVICE_AUDIENCE,
    })
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_target"


@pytest.mark.asyncio
async def test_revoked_device_or_grant_refuses_refresh_and_channel(client, db):
    user = await user_named(db, "device-owner")
    device, refresh = await device_with_grant(db, user)
    token = (await _refresh(client, refresh, DEVICE_AUDIENCE)).json()

    device.status = DEVICE_STATUS_REVOKED
    await db.flush()
    assert (await _refresh(client, token["refresh_token"], DEVICE_AUDIENCE)).status_code == 400
    assert await resolve_device_credential(db, token["access_token"]) == "device_revoked"

    other, other_refresh = await device_with_grant(db, user, name="Other")
    other_token = (await _refresh(client, other_refresh, DEVICE_AUDIENCE)).json()
    await revoke_device_grant(db, other.grant_id)
    assert await resolve_device_credential(db, other_token["access_token"]) == "device_grant_revoked"
    assert (await _refresh(client, other_token["refresh_token"], DEVICE_AUDIENCE)).status_code == 400


@pytest.mark.asyncio
async def test_absolute_lifetime_ends_the_device_grant(client, db):
    user = await user_named(db, "device-owner")
    device, refresh = await device_with_grant(db, user)
    grant = await db.get(OAuthGrant, device.grant_id)
    grant.created_at = utc_now() - timedelta(days=91)
    await db.flush()
    response = await _refresh(client, refresh, DEVICE_AUDIENCE)
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_channel_refuses_other_audiences_and_missing_scope(db):
    user = await user_named(db, "device-owner")
    device, _refresh_token = await device_with_grant(db, user)
    gateway, _ = mint_access_token(user_id=user.id, client_id="octryx-test-client", grant_id=device.grant_id,
                                   scopes=["device:connect"], resource=GATEWAY_AUDIENCE)
    assert await resolve_device_credential(db, gateway) == "device_token_invalid"
    no_scope, _ = mint_access_token(user_id=user.id, client_id="octryx-test-client", grant_id=device.grant_id,
                                    scopes=["model:invoke"], resource=DEVICE_AUDIENCE)
    assert await resolve_device_credential(db, no_scope) == "device_scope_missing"
    other = await user_named(db, "someone-else")
    forged, _ = mint_access_token(user_id=other.id, client_id="octryx-test-client", grant_id=device.grant_id,
                                  scopes=["device:connect"], resource=DEVICE_AUDIENCE)
    assert await resolve_device_credential(db, forged) == "device_token_invalid"
    assert await resolve_device_credential(db, "") == "device_token_invalid"


@pytest.mark.asyncio
async def test_password_change_and_deactivation_revoke_every_device_grant(client, db):
    await oauth_client(db)
    user = await user_named(db, "device-owner")
    first, _ = await device_with_grant(db, user)
    second, _ = await device_with_grant(db, user, name="Second")
    assert await revoke_user_device_grants(db, user_id=user.id) == 2
    for device in (first, second):
        assert (await db.get(OAuthGrant, device.grant_id)).revoked_at is not None
        await db.refresh(device)
        assert device.status == DEVICE_STATUS_REVOKED  # so the device key cannot renew it either
    assert await revoke_user_device_grants(db, user_id=user.id) == 0
