"""Phone session lifetime: revoking, credential changes, password resets and sign-out end the phone, and the device login validity caps phones and Macs."""

from __future__ import annotations

import time
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import AuditLog, MobileDevice, UserDevice
from app.models.security.oauth_provider import OAuthGrant
from app.services.devices.credential import device_grant_refusal, revoke_user_device_grants
from app.services.devices.login_validity import parse_validity
from app.services.devices.renewal import renew_device_credential, renewal_payload
from app.time_utils import utc_now
from tests.devices.device_support import (
    device_with_grant,
    gateway_login_token,
    member_with_headers,
    new_key_pair,
    registration_body,
    user_named,
)
from tests.mobile.mobile_pairing_support import _cookie_header, _paired_phone


async def _web_headers(client, db, user) -> dict[str, str]:
    from app.services.auth import create_access_token

    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.mark.asyncio
async def test_revoking_cuts_the_phone_off_on_its_next_request(client, db):
    user, _mac, claimed = await _paired_phone(client, db)
    cookie = _cookie_header(claimed)
    assert (await client.get("/api/v1/devices", headers={"cookie": cookie})).status_code == 200
    phone = (await db.execute(select(MobileDevice).where(MobileDevice.owner_user_id == user.id))).scalar_one()

    revoked = await client.post(f"/api/v1/mobile/devices/{phone.id}/revoke", headers={"cookie": cookie})
    assert revoked.status_code == 200
    # The five-minute access token is still unexpired, yet every authenticated request is refused now.
    assert (await client.get("/api/v1/devices", headers={"cookie": cookie})).status_code == 401
    session = await client.post("/api/v1/mobile/session", headers={"cookie": cookie})
    assert session.status_code == 401 and session.json()["reason"] == "mobile_device_revoked"
    assert any("octryx_mobile=" in header and "Max-Age=0" in header for header in session.headers.get_list("set-cookie"))


@pytest.mark.parametrize(("text", "ok"), [("1h", True), ("12h", True), ("1d", True), ("90d", True), ("365d", True),
                                          ("366d", False), ("0h", False), ("30m", False), ("never", False),
                                          ("", False), ("8761h", False)])
def test_validity_bounds(text, ok):
    assert (parse_validity(text) is not None) is ok


@pytest.mark.asyncio
async def test_only_admins_set_the_validity_and_it_cuts_old_phones(client, db, auth_headers):
    user, _mac, claimed = await _paired_phone(client, db)
    cookie = _cookie_header(claimed)
    _member, member_headers = await member_with_headers(client, db, "plain-member")
    assert (await client.put("/api/v1/admin/devices/login-validity", json={"validity": "1d"},
                             headers=member_headers)).status_code == 403
    for bad in ("never", "0h", "400d", None):
        refused = await client.put("/api/v1/admin/devices/login-validity", json={"validity": bad}, headers=auth_headers)
        assert refused.status_code == 400 and refused.json()["reason"] == "device_login_validity_invalid"
    stored = await client.put("/api/v1/admin/devices/login-validity", json={"validity": "1H"}, headers=auth_headers)
    assert stored.status_code == 200 and stored.json()["validity"] == "1h"
    assert (await client.get("/api/v1/admin/devices/login-validity", headers=auth_headers)).json()["validity"] == "1h"

    phone = (await db.execute(select(MobileDevice).where(MobileDevice.owner_user_id == user.id))).scalar_one()
    phone.created_at = utc_now() - timedelta(hours=2)
    await db.flush()
    session = await client.post("/api/v1/mobile/session", headers={"cookie": cookie})
    assert session.status_code == 401 and session.json()["reason"] == "mobile_login_expired"
    assert (await client.get("/api/v1/devices", headers={"cookie": cookie})).status_code == 401
    audited = (await db.execute(select(AuditLog).where(AuditLog.action == "admin.devices.login_validity"))).scalars()
    assert [row.details["value"] for row in audited] == ["1h"]


@pytest.mark.asyncio
async def test_the_validity_caps_a_mac_and_device_enable_replaces_the_expired_one(client, db, auth_headers):
    user = await user_named(db, "mac-owner")
    device, _refresh = await device_with_grant(db, user, name="MacBook")
    grant = await db.get(OAuthGrant, device.grant_id)
    assert await device_grant_refusal(db, grant) == ""
    device.created_at = utc_now() - timedelta(days=91)  # the default validity is 90 days
    await db.flush()
    assert await device_grant_refusal(db, grant) == "device_login_expired"

    private, public = new_key_pair()
    device.public_key = public
    issued = int(time.time())
    import base64

    signature = base64.urlsafe_b64encode(private.sign(renewal_payload(device.id, issued))).decode().rstrip("=")
    grant.created_at = utc_now() - timedelta(minutes=10)
    await db.flush()
    refused = await renew_device_credential(db, {"device_id": device.id, "issued_at": issued, "signature": signature},
                                            now=time.time())
    assert refused == "device_login_expired"  # renewal never extends a device beyond the validity

    listed = await client.get("/api/v1/devices", headers=await _web_headers(client, db, user))
    [row] = listed.json()["items"]
    assert row["needs_login"] and row["login_expires_at"]

    login = await gateway_login_token(db, user)
    again = await client.post("/api/v1/devices", json=registration_body("MacBook"),
                              headers={"Authorization": f"Bearer {login}"})
    assert again.status_code == 201, again.text  # the expired registration of the same name made room
    old = await db.get(UserDevice, device.id)
    assert old.status == "revoked" and old.revoke_reason == "device login expired"


@pytest.mark.asyncio
async def test_a_credential_change_ends_every_phone(client, db):
    user, _mac, claimed = await _paired_phone(client, db)
    await revoke_user_device_grants(db, user_id=user.id)
    await db.flush()
    session = await client.post("/api/v1/mobile/session", headers={"cookie": _cookie_header(claimed)})
    assert session.status_code == 401 and session.json()["reason"] == "mobile_device_revoked"


@pytest.mark.asyncio
async def test_revoking_the_octryx_claude_login_ends_the_phone(client, db):
    user, _mac, claimed = await _paired_phone(client, db)
    phone = (await db.execute(select(MobileDevice).where(MobileDevice.owner_user_id == user.id))).scalar_one()
    grant = await db.get(OAuthGrant, phone.grant_id)
    grant.revoked_at = utc_now()
    await db.flush()
    session = await client.post("/api/v1/mobile/session", headers={"cookie": _cookie_header(claimed)})
    assert session.status_code == 401 and session.json()["reason"] == "mobile_device_revoked"


@pytest.mark.asyncio
async def test_an_admin_password_reset_ends_the_phones(client, db, auth_headers):
    from app.services.admin.governance.admin_user_service import reset_user_password

    user, _mac, claimed = await _paired_phone(client, db)
    admin = await user_named(db, "some-admin")
    await reset_user_password(db, admin_id=admin.id, user_id=user.id, password="New-password-1")
    session = await client.post("/api/v1/mobile/session", headers={"cookie": _cookie_header(claimed)})
    assert session.status_code == 401 and session.json()["reason"] == "mobile_device_revoked"
