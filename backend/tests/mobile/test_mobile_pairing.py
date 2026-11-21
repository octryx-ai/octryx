"""Octryx Mobile: pairing a phone with the QR code from the Mac, the phone's session, revoking,
the platform's device login validity (phones and Macs) and the phone's view of usage.

- the Mac's own octryx-claude login creates the pairing; the code sits in the URL fragment; it scans once, within
  two minutes; the Mac sees the phone and the two-digit number and must confirm (a denied or foreign pairing gets
  nothing); the claim is handed out once and redeemed once;
- the phone's credential is an httpOnly SameSite=Strict cookie for ``/api/v1/mobile`` only; its access token lives
  five minutes and is refused on the next request once the phone is revoked or expired;
- the validity is ``<n>h``/``<n>d`` between 1 hour and 365 days, admin only, audited, and applies to Macs too: an
  expired Mac can neither refresh nor renew, and ``device enable`` replaces the expired registration.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import AuditLog, MobileDevice, MobilePairing
from app.models.security.oauth_provider import OAuthGrant
from app.services.mobile.contract import MOBILE_COOKIE
from app.time_utils import utc_now
from tests.devices.device_support import device_with_grant, user_named
from tests.mobile.mobile_pairing_support import (
    CONFIRM,
    PAIRINGS,
    _browser,
    _cookie_header,
    _cookies,
    _mac_headers,
    _paired_phone,
)


@pytest.mark.asyncio
async def test_the_whole_pairing_from_qr_code_to_phone_session(client, db):
    user = await user_named(db, "mobile-owner")
    mac = await _mac_headers(db, user)
    created = await client.post(PAIRINGS, headers=mac)
    assert created.status_code == 201 and created.headers["cache-control"] == "no-store"
    url = created.json()["url"]
    assert url.startswith("http://test/m/pair#c=")  # the code only in the fragment, never in a request line
    code = url.split("#c=", 1)[1]
    pairing_id = created.json()["pairing_id"]
    assert (await client.get(f"{PAIRINGS}/{pairing_id}", headers=mac)).json()["state"] == "pending"

    scanned = await client.post("/api/v1/mobile/pairings/scan", json={"code": code},
                                headers={"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X)"})
    assert scanned.status_code == 200, scanned.text
    number, secret = scanned.json()["match_number"], scanned.json()["scan_secret"]
    assert len(number) == 2 and number.isdigit()
    view = (await client.get(f"{PAIRINGS}/{pairing_id}", headers=mac)).json()
    assert view["state"] == "scanned" and view["match_number"] == number and view["phone"] == "iPhone"
    again = await client.post("/api/v1/mobile/pairings/scan", json={"code": code})
    assert again.status_code == 409 and again.json()["reason"] == "mobile_pairing_used"  # one scan only

    waiting = await client.post(f"/api/v1/mobile/pairings/{pairing_id}/status", json={"scan_secret": secret})
    assert waiting.json() == {"state": "waiting", "match_number": number}
    wrong = await client.post(f"/api/v1/mobile/pairings/{pairing_id}/status", json={"scan_secret": "x" * 43})
    assert wrong.status_code == 404

    assert (await client.post(CONFIRM.format(pairing_id), json={"approve": True},
                              headers=_browser(user))).status_code == 200
    status = await client.post(f"/api/v1/mobile/pairings/{pairing_id}/status", json={"scan_secret": secret})
    claim_code = status.json()["claim"]
    assert status.json()["state"] == "confirmed" and len(claim_code) == 9 and claim_code[4] == "-"
    twice = await client.post(f"/api/v1/mobile/pairings/{pairing_id}/status", json={"scan_secret": secret})
    assert twice.status_code == 409  # the claim is handed out once

    claimed = await client.post("/api/v1/mobile/claim", json={"claim": claim_code.lower().replace("-", " ")})
    assert claimed.status_code == 201, claimed.text  # typed by hand: case, separator and spaces do not matter
    jar = _cookies(claimed)
    phone_cookie = jar[MOBILE_COOKIE][MOBILE_COOKIE]
    assert phone_cookie["httponly"] and phone_cookie["samesite"].lower() == "strict"
    assert phone_cookie["path"] == "/api/v1/mobile"
    access = jar["octryx_phone_access"]["octryx_phone_access"]  # the phone's own cookie, never the web login's access_token
    assert int(access["max-age"]) == 300 and access["httponly"] and access["path"] == "/"
    assert "access_token" not in jar
    reused = await client.post("/api/v1/mobile/claim", json={"claim": claim_code})
    assert reused.status_code == 403

    cookie = _cookie_header(claimed)
    phones = await client.get("/api/v1/mobile/devices", headers={"cookie": cookie})
    assert phones.status_code == 200, phones.text
    [phone] = phones.json()["items"]
    assert phone["name"] == "iPhone" and phone["this_device"] and phone["login_expires_at"]
    session = await client.post("/api/v1/mobile/session", headers={"cookie": cookie})
    assert session.status_code == 200 and session.json()["device"]["id"] == phone["id"]
    assert "octryx_phone_access" in _cookies(session) and "access_token" not in _cookies(session)
    actions = set((await db.execute(select(AuditLog.action).where(AuditLog.user_id == user.id))).scalars())
    assert {"mobile.pairing.created", "mobile.pairing.scanned", "mobile.pairing.confirmed",
            "mobile.device.paired"} <= actions


@pytest.mark.asyncio
async def test_a_denied_expired_or_foreign_pairing_gives_nothing(client, db):
    owner = await user_named(db, "mobile-owner")
    other = await user_named(db, "someone-else")
    mac = await _mac_headers(db, owner)
    foreign = await _mac_headers(db, other)
    created = (await client.post(PAIRINGS, headers=mac)).json()
    code, pairing_id = created["url"].split("#c=", 1)[1], created["pairing_id"]
    assert (await client.get(f"{PAIRINGS}/{pairing_id}", headers=foreign)).status_code == 404
    scanned = (await client.post("/api/v1/mobile/pairings/scan", json={"code": code})).json()
    assert (await client.post(CONFIRM.format(pairing_id), json={"approve": True},
                              headers=_browser(other))).status_code == 404
    assert (await client.post(CONFIRM.format(pairing_id), json={"approve": False},
                              headers=_browser(owner))).status_code == 200
    denied = await client.post(f"/api/v1/mobile/pairings/{pairing_id}/status",
                               json={"scan_secret": scanned["scan_secret"]})
    assert denied.status_code == 403 and denied.json()["reason"] == "mobile_pairing_denied"

    late = (await client.post(PAIRINGS, headers=mac)).json()
    row = await db.get(MobilePairing, late["pairing_id"])
    row.expires_at = utc_now() - timedelta(seconds=1)
    await db.flush()
    expired = await client.post("/api/v1/mobile/pairings/scan", json={"code": late["url"].split("#c=", 1)[1]})
    assert expired.status_code == 410 and expired.json()["reason"] == "mobile_pairing_expired"


@pytest.mark.asyncio
async def test_a_mac_device_credential_never_pairs_a_phone(client, db):
    user = await user_named(db, "mobile-owner")
    device, _refresh = await device_with_grant(db, user)
    from app.services.agent_gateway.contract import GATEWAY_AUDIENCE
    from app.services.oauth_provider import mint_access_token

    token, _ = mint_access_token(user_id=user.id, client_id="octryx-test-client", grant_id=device.grant_id,
                                 scopes=["model:invoke"], resource=GATEWAY_AUDIENCE)
    refused = await client.post(PAIRINGS, headers={"Authorization": f"Bearer {token}"})
    assert refused.status_code == 403 and refused.json()["reason"] == "device_login_required"


@pytest.mark.asyncio
async def test_guessing_codes_is_rate_limited(client, db):
    statuses = [(await client.post("/api/v1/mobile/claim", json={"claim": f"ABCD-EF{n:02d}"})).status_code
                for n in range(7)]
    assert statuses[:5] == [403] * 5 and statuses[-1] == 429


@pytest.mark.parametrize(("typed", "code"), [("k7q4-xm9p", "K7Q4XM9P"), ("K7Q4 XM9P", "K7Q4XM9P"),
                                             ("o1il-0000", "0111" + "0000"), ("K7Q4-XM9", ""), ("K7Q4-XM9U", ""),
                                             (None, "")])
def test_typed_claim_codes_are_normalized(typed, code):
    from app.services.mobile.pairing import normalize_claim_code

    assert normalize_claim_code(typed) == code


@pytest.mark.asyncio
async def test_a_model_only_token_cannot_pair_and_pairings_are_capped(client, db):
    user = await user_named(db, "mobile-owner")
    narrow = await _mac_headers(db, user, scopes=["model:invoke"])
    refused = await client.post(PAIRINGS, headers=narrow)
    assert refused.status_code == 403 and refused.json()["reason"] == "mobile_pairing_scope_missing"
    mac = await _mac_headers(db, user)
    statuses = [(await client.post(PAIRINGS, headers=mac)).status_code for _ in range(6)]
    assert statuses == [201] * 5 + [429]


# --- pairing hardening -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_only_the_signed_in_browser_confirms_never_a_token(client, db):
    from app.services.auth import create_access_token

    user = await user_named(db, "mobile-owner")
    mac = await _mac_headers(db, user)
    created = (await client.post(PAIRINGS, headers=mac)).json()
    assert created["confirm_url"] == f"http://test/m/confirm?p={created['pairing_id']}"
    code, pairing_id = created["url"].split("#c=", 1)[1], created["pairing_id"]
    await client.post("/api/v1/mobile/pairings/scan", json={"code": code})
    # The Mac's gateway token (which a tool or an agent may hold) has no way to confirm.
    assert (await client.post(f"{PAIRINGS}/{pairing_id}/confirm", json={"approve": True}, headers=mac)).status_code in (
        404, 405)
    # Neither does a web bearer token or an API key: only the browser's own cookie.
    bearer = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    for headers in (bearer, {**_browser(user), **bearer}, {**_browser(user), "X-API-Key": "oek_x"}):
        refused = await client.post(CONFIRM.format(pairing_id), json={"approve": True}, headers=headers)
        assert refused.status_code in (401, 403)
    view = await client.get(f"/api/v1/mobile/pairings/{pairing_id}", headers=_browser(user))
    assert view.status_code == 200 and view.json()["state"] == "scanned" and view.json()["match_number"]
    assert (await client.post(CONFIRM.format(pairing_id), json={"approve": True},
                              headers=_browser(user))).status_code == 200


@pytest.mark.asyncio
async def test_a_phone_never_confirms_a_pairing(client, db):
    user, mac, claimed = await _paired_phone(client, db)
    created = (await client.post(PAIRINGS, headers=mac)).json()
    await client.post("/api/v1/mobile/pairings/scan", json={"code": created["url"].split("#c=", 1)[1]})
    phone = {"cookie": _cookie_header(claimed)}
    refused = await client.post(CONFIRM.format(created["pairing_id"]), json={"approve": True}, headers=phone)
    assert refused.status_code in (401, 403)


@pytest.mark.asyncio
async def test_signing_out_of_the_platform_ends_the_phone_and_pairing_needs_a_live_login(client, db):
    from app.models import RefreshToken

    user, _mac, claimed = await _paired_phone(client, db)
    phone = (await db.execute(select(MobileDevice).where(MobileDevice.owner_user_id == user.id))).scalar_one()
    pairing = (await db.execute(select(MobilePairing).where(MobilePairing.mobile_device_id == phone.id))).scalar_one()
    assert pairing.state == "claimed"  # the pairing names the device it created
    grant = await db.get(OAuthGrant, phone.grant_id)
    web = await db.get(RefreshToken, grant.platform_refresh_token_id)
    web.revoked_at = utc_now()  # the person signed out of the platform
    await db.flush()
    session = await client.post("/api/v1/mobile/session", headers={"cookie": _cookie_header(claimed)})
    assert session.status_code == 401 and session.json()["reason"] == "mobile_login_expired"
    stale = await client.post(PAIRINGS, headers={"Authorization": _mac["Authorization"]})
    assert stale.status_code == 403 and stale.json()["reason"] == "mobile_pairing_login_required"
