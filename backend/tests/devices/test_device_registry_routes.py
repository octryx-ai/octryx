"""Device registration and management: owner-only management, folders only narrow on the platform,
admins see no folders and revoke with a reason, a device credential never registers another device."""

from __future__ import annotations

import base64

import pytest
from sqlalchemy import select

from app.models import AuditLog, UserDevice
from app.models.security.oauth_provider import OAuthGrant
from app.services.agent_gateway.contract import GATEWAY_AUDIENCE
from app.services.devices.contract import DEVICE_AUDIENCE
from tests.devices.device_support import (
    gateway_login_token,
    member_with_headers,
    registration_body,
    user_named,
)


async def _register(client, token: str, **overrides):
    return await client.post("/api/v1/devices", json=registration_body(**overrides),
                             headers={"Authorization": f"Bearer {token}"})


async def _refresh(client, refresh_token: str, resource: str):
    return await client.post("/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": "octryx-test-client",
        "resource": resource})


@pytest.mark.asyncio
async def test_register_returns_the_device_credential_once_and_lists_for_the_owner_only(client, db):
    owner, owner_headers = await member_with_headers(client, db, "device-owner")
    _other, other_headers = await member_with_headers(client, db, "other-member")
    response = await _register(client, await gateway_login_token(db, owner))
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["credential"]["audience"] == DEVICE_AUDIENCE
    assert set(body["credential"]["scopes"]) == {"device:connect", "model:invoke", "knowledge:read"}
    device_id = body["device"]["id"]
    assert device_id.startswith("dev_")
    assert (await db.get(OAuthGrant, (await db.get(UserDevice, device_id)).grant_id)).device_id == device_id

    mine = (await client.get("/api/v1/devices", headers=owner_headers)).json()
    assert [item["id"] for item in mine["items"]] == [device_id]
    assert mine["items"][0]["folders"] == ["/home/sample/src/one", "/home/sample/src/two"]
    assert (await client.get("/api/v1/devices", headers=other_headers)).json()["items"] == []
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "device.registered"))).scalars().all()
    assert [row.resource_id for row in audit] == [device_id]


@pytest.mark.asyncio
async def test_a_device_credential_cannot_register_another_device(client, db):
    owner = await user_named(db, "device-owner")
    registered = (await _register(client, await gateway_login_token(db, owner))).json()
    gateway = (await _refresh(client, registered["credential"]["refresh_token"], GATEWAY_AUDIENCE)).json()
    response = await _register(client, gateway["access_token"], name="Second")
    assert response.status_code == 403
    assert response.json() == {"state": "needs_configuration", "reason": "device_login_required"}


@pytest.mark.asyncio
async def test_registration_validation_refuses_with_fixed_codes(client, db):
    owner = await user_named(db, "device-owner")
    token = await gateway_login_token(db, owner)
    assert (await _register(client, token)).status_code == 201
    taken = await _register(client, token, name="TEST DEVICE")
    assert taken.json()["reason"] == "device_name_taken"
    assert (await _register(client, token, name="x", public_key="short")).json()["reason"] == \
        "device_public_key_invalid"
    assert (await _register(client, token, name="y", folders=["relative/path"])).json()["reason"] == \
        "device_folders_invalid"
    assert (await _register(client, token, name="z", folders=["/a/../etc"])).json()["reason"] == \
        "device_folders_invalid"
    assert (await _register(client, token, name="w", profiles_available=["root"])).json()["reason"] == \
        "device_profiles_invalid"
    assert (await _register(client, token, name="v", max_parallel_jobs=9)).json()["reason"] == \
        "device_parallel_jobs_invalid"
    assert (await client.post("/api/v1/devices", json=registration_body())).status_code == 401


@pytest.mark.asyncio
async def test_only_the_owner_manages_and_the_platform_only_narrows_folders(client, db):
    owner, owner_headers = await member_with_headers(client, db, "device-owner")
    _other, other_headers = await member_with_headers(client, db, "other-member")
    device_id = (await _register(client, await gateway_login_token(db, owner))).json()["device"]["id"]
    url = f"/api/v1/devices/{device_id}"

    for response in (
        await client.patch(url, json={"name": "Mine now"}, headers=other_headers),
        await client.post(f"{url}/revoke", headers=other_headers),
    ):
        assert response.status_code == 404
        assert response.json()["reason"] == "device_not_found"

    widened = await client.patch(url, json={"folders": ["/home/sample/src/one", "/etc"]}, headers=owner_headers)
    assert widened.json()["reason"] == "device_folders_platform_cannot_add"
    narrowed = await client.patch(url, json={"folders": ["/home/sample/src/two"], "name": "Renamed"},
                                  headers=owner_headers)
    assert narrowed.status_code == 200, narrowed.text
    assert narrowed.json()["folders"] == ["/home/sample/src/two"]
    assert narrowed.json()["name"] == "Renamed"
    assert (await client.patch(url, json={"command": "rm"}, headers=owner_headers)).status_code == 400

    paused = await client.put("/api/v1/devices/pause", json={"paused": True}, headers=owner_headers)
    assert paused.json()["all_paused"] is True and paused.json()["items"][0]["paused"] is True


@pytest.mark.asyncio
async def test_owner_revoke_ends_the_credential(client, db):
    owner, owner_headers = await member_with_headers(client, db, "device-owner")
    registered = (await _register(client, await gateway_login_token(db, owner))).json()
    device_id = registered["device"]["id"]
    revoked = await client.post(f"/api/v1/devices/{device_id}/revoke", headers=owner_headers)
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
    assert (await _refresh(client, registered["credential"]["refresh_token"], DEVICE_AUDIENCE)).status_code == 400
    assert (await client.get("/api/v1/devices", headers=owner_headers)).json()["items"] == []
    renamed = await client.patch(f"/api/v1/devices/{device_id}", json={"name": "Back"}, headers=owner_headers)
    assert renamed.json()["reason"] == "device_revoked"


@pytest.mark.asyncio
async def test_device_disables_itself_with_its_channel_token(client, db):
    owner = await user_named(db, "device-owner")
    registered = (await _register(client, await gateway_login_token(db, owner))).json()
    channel = (await _refresh(client, registered["credential"]["refresh_token"], DEVICE_AUDIENCE)).json()
    gateway = (await _refresh(client, channel["refresh_token"], GATEWAY_AUDIENCE)).json()
    assert (await client.post("/api/v1/devices/self/disable",
                              headers={"Authorization": f"Bearer {gateway['access_token']}"})).status_code == 401
    disabled = await client.post("/api/v1/devices/self/disable",
                                 headers={"Authorization": f"Bearer {channel['access_token']}"})
    assert disabled.status_code == 200
    assert (await db.get(UserDevice, registered["device"]["id"])).status == "revoked"


@pytest.mark.asyncio
async def test_admins_see_devices_without_folders_and_revoke_with_a_reason(client, db, auth_headers):
    owner, _owner_headers = await member_with_headers(client, db, "device-owner")
    _other, other_headers = await member_with_headers(client, db, "other-member")
    device_id = (await _register(client, await gateway_login_token(db, owner))).json()["device"]["id"]

    listed = (await client.get("/api/v1/admin/devices", headers=auth_headers)).json()["items"]
    entry = next(item for item in listed if item["id"] == device_id)
    assert "folders" not in entry and entry["folder_count"] == 2 and entry["owner_user_id"] == owner.id
    assert (await client.get("/api/v1/admin/devices", headers=other_headers)).status_code == 403
    # An admin manages devices only through the admin route: the owner routes answer device_not_found.
    assert (await client.patch(f"/api/v1/devices/{device_id}", json={"paused": True},
                               headers=auth_headers)).status_code == 404

    url = f"/api/v1/admin/devices/{device_id}/revoke"
    assert (await client.post(url, json={}, headers=auth_headers)).json()["reason"] == "revoke_reason_required"
    assert (await client.post(url, json={"reason": "lost laptop"}, headers=other_headers)).status_code == 403
    revoked = await client.post(url, json={"reason": "lost laptop"}, headers=auth_headers)
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "device.revoked"))).scalar_one()
    assert audit.details["by_owner"] is False and audit.details["reason"] == "lost laptop"


@pytest.mark.asyncio
async def test_a_retry_after_a_lost_answer_takes_its_own_entry_over_with_a_proven_key(client, db):
    """The server may register the device while the launcher's answer times out, so the retry meets its own entry
    as device_name_taken. A retry signed with the same device key is the same device."""
    from app.services.devices.registration_retry import registration_payload
    from tests.devices.device_support import new_key_pair

    owner = await user_named(db, "device-owner")
    token = await gateway_login_token(db, owner)
    private, public = new_key_pair()
    first = await _register(client, token, public_key=public)
    assert first.status_code == 201
    device_id, lost_refresh = first.json()["device"]["id"], first.json()["credential"]["refresh_token"]

    unsigned = await _register(client, token, public_key=public, folders=["/home/sample/src/one"])
    assert unsigned.json()["reason"] == "device_name_taken"  # the public key alone proves nothing
    proof = base64.urlsafe_b64encode(private.sign(registration_payload("Test device", public))).decode().rstrip("=")
    _other_private, other_public = new_key_pair()
    assert (await _register(client, token, public_key=other_public, key_proof=proof)).json()["reason"] == \
        "device_name_taken"  # another key with a borrowed proof

    retried = await _register(client, token, public_key=public, key_proof=proof, folders=["/home/sample/src/one"])
    assert retried.status_code == 201, retried.text
    assert retried.json()["device"]["id"] == device_id
    devices = (await db.execute(select(UserDevice).where(UserDevice.owner_user_id == owner.id))).scalars().all()
    assert [d.id for d in devices] == [device_id] and devices[0].folders == ["/home/sample/src/one"]
    assert (await _refresh(client, lost_refresh, DEVICE_AUDIENCE)).status_code != 200  # the lost credential is dead
    fresh = await _refresh(client, retried.json()["credential"]["refresh_token"], DEVICE_AUDIENCE)
    assert fresh.status_code == 200
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "device.registration_retried"))).scalars()
    assert [row.resource_id for row in audit] == [device_id]
