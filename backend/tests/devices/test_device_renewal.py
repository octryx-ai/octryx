"""Device credential renewal with the device key: a lost or replayed refresh token never strands an
active device, while a revoked device, a foreign key, a stale or replayed request and a credential change are
refused."""

from __future__ import annotations

import base64
import time

import pytest
from sqlalchemy import event

from app.models import UserDevice
from app.models.security.oauth_provider import OAuthGrant
from app.services.devices.contract import DEVICE_AUDIENCE
from app.services.devices.credential import revoke_device_grant, revoke_user_device_grants
from app.services.devices.renewal import renew_device_credential, renewal_payload
from tests.devices.device_support import (
    device_with_grant,
    keyed_device,
    member_with_headers,
    new_key_pair,
    user_named,
)

RENEW_PATH = "/api/v1/devices/self/renew"


async def _keyed_device(db, user):
    device, refresh = await device_with_grant(db, user)
    private, public = new_key_pair()
    device.public_key = public
    await db.flush()
    return device, refresh, private


def _signed(private, device_id: str, issued_at: int | None = None) -> dict:
    issued_at = int(time.time()) if issued_at is None else issued_at
    signature = private.sign(renewal_payload(device_id, issued_at))
    return {"device_id": device_id, "issued_at": issued_at,
            "signature": base64.urlsafe_b64encode(signature).decode().rstrip("=")}


async def _refresh(client, refresh_token: str):
    return await client.post("/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": "octryx-test-client",
        "resource": DEVICE_AUDIENCE,
    })


@pytest.mark.asyncio
async def test_a_replay_killed_grant_is_renewed_with_the_device_key(client, db):
    device, refresh, private = await _keyed_device(db, await user_named(db, "device-owner"))
    rotated = (await _refresh(client, refresh)).json()
    # The rotated token got lost on the way: the client retries the old one, the platform kills the grant.
    assert (await _refresh(client, refresh)).status_code == 400
    assert (await _refresh(client, rotated["refresh_token"])).status_code == 400
    old_grant_id = device.grant_id

    request = _signed(private, device.id, int(time.time()) + 1)
    response = await client.post(RENEW_PATH, json=request)

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    credential = response.json()["credential"]
    assert credential["client_id"] == "octryx-test-client" and "device:connect" in credential["scopes"]
    fresh = await _refresh(client, credential["refresh_token"])
    assert fresh.status_code == 200, fresh.text
    await db.refresh(device)
    assert device.grant_id != old_grant_id
    assert (await db.get(OAuthGrant, old_grant_id)).revoked_at is not None
    # The same signed request cannot be replayed: it is not newer than the grant it created.
    replayed = await client.post(RENEW_PATH, json=request)
    assert replayed.status_code == 401 and replayed.json()["reason"] == "device_renewal_stale"


@pytest.mark.asyncio
async def test_a_revoked_device_cannot_renew(client, db):
    device, _refresh_token, private = await _keyed_device(db, await user_named(db, "device-owner"))
    device.status = "revoked"
    await revoke_device_grant(db, device.grant_id)
    await db.flush()

    response = await client.post(RENEW_PATH, json=_signed(private, device.id, int(time.time()) + 1))

    assert response.status_code == 403
    assert response.json() == {"state": "unauthorized", "reason": "device_revoked"}


@pytest.mark.asyncio
async def test_a_foreign_key_or_a_stale_request_is_refused(client, db):
    device, _refresh_token, _private = await _keyed_device(db, await user_named(db, "device-owner"))
    grant_id = device.grant_id
    foreign, _public = new_key_pair()

    forged = await client.post(RENEW_PATH, json=_signed(foreign, device.id, int(time.time()) + 1))
    assert forged.status_code == 403 and forged.json()["reason"] == "device_signature_invalid"

    _device2, _refresh2, private = await _keyed_device(db, await user_named(db, "other-owner"))
    stale = await client.post(RENEW_PATH, json=_signed(private, _device2.id, int(time.time()) - 3600))
    assert stale.status_code == 401 and stale.json()["reason"] == "device_renewal_stale"
    malformed = await client.post(RENEW_PATH, json={"device_id": device.id, "issued_at": "1", "signature": "x"})
    assert malformed.status_code == 401 and malformed.json()["reason"] == "device_renewal_invalid"
    assert (await db.get(UserDevice, device.id)).grant_id == grant_id


@pytest.mark.asyncio
async def test_a_credential_change_revokes_the_device_so_the_key_cannot_renew(client, db):
    user = await user_named(db, "device-owner")
    device, _refresh_token, private = await _keyed_device(db, user)

    await revoke_user_device_grants(db, user_id=user.id)
    await db.flush()

    response = await client.post(RENEW_PATH, json=_signed(private, device.id, int(time.time()) + 1))
    assert response.status_code == 403 and response.json()["reason"] == "device_revoked"


@pytest.mark.asyncio
async def test_the_owner_sees_needs_login_while_the_credential_is_dead(client, db):
    user, headers = await member_with_headers(client, db, "device-owner")
    device, _refresh_token, private = await _keyed_device(db, user)

    listed = (await client.get("/api/v1/devices", headers=headers)).json()["items"]
    assert listed[0]["needs_login"] is False

    await revoke_device_grant(db, device.grant_id)
    await db.flush()
    listed = (await client.get("/api/v1/devices", headers=headers)).json()["items"]
    assert listed[0]["needs_login"] is True

    assert (await client.post(RENEW_PATH, json=_signed(private, device.id, int(time.time()) + 1))).status_code == 200
    listed = (await client.get("/api/v1/devices", headers=headers)).json()["items"]
    assert listed[0]["needs_login"] is False


@pytest.mark.asyncio
async def test_renewal_locks_the_device_row(db):
    """Concurrent renewals are serialized on the device row, so exactly one grant stays live."""
    user = await user_named(db, "device-owner")
    device, _private, _token = await keyed_device(db, user)
    locked: list[bool] = []

    def record(orm_execute_state) -> None:
        if orm_execute_state.is_select:
            locked.append(orm_execute_state.statement._for_update_arg is not None)

    event.listen(db.sync_session, "do_orm_execute", record)
    try:
        await renew_device_credential(db, {"device_id": device.id, "issued_at": int(time.time()),
                                           "signature": "invalid"}, now=time.time())
    finally:
        event.remove(db.sync_session, "do_orm_execute", record)

    assert locked and locked[0] is True  # the first read of the renewal is the device row, FOR UPDATE
