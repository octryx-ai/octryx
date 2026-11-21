"""Shared helpers for the test_mobile_pairing_* modules."""

from __future__ import annotations

from datetime import timedelta
from http.cookies import SimpleCookie

from app.models.security.oauth_provider import OAuthGrant
from app.time_utils import utc_now
from tests.devices.device_support import user_named

PAIRINGS = "/api/v1/agent-gateway/mobile/pairings"


CONFIRM = "/api/v1/mobile/pairings/{}/confirm"


async def _mac_headers(db, user, *, scopes=None) -> dict[str, str]:
    """The Mac's octryx-claude login, tied to a live web login (as an interactive login is)."""
    from app.models import RefreshToken
    from app.services.agent_gateway.contract import GATEWAY_AUDIENCE
    from app.services.oauth_provider import mint_access_token
    from tests.devices.device_support import GATEWAY_LOGIN_SCOPES, oauth_client

    client_row = await oauth_client(db)
    import uuid

    web = RefreshToken(user_id=user.id, token_hash=f"test-{uuid.uuid4().hex}", expires_at=utc_now() + timedelta(days=30))
    db.add(web)
    await db.flush()
    granted = scopes or GATEWAY_LOGIN_SCOPES
    grant = OAuthGrant(user_id=user.id, client_id=client_row.client_id, scopes=granted,
                       platform_refresh_token_id=web.id)
    db.add(grant)
    await db.flush()
    token, _ = mint_access_token(user_id=user.id, client_id=client_row.client_id, grant_id=grant.id, scopes=granted,
                                 resource=GATEWAY_AUDIENCE)
    return {"Authorization": f"Bearer {token}"}


def _browser(user) -> dict[str, str]:
    """The person's signed-in browser on the Mac: the web session cookie (and the harness's same-origin header)."""
    from app.services.auth import create_access_token

    return {"cookie": f"access_token={create_access_token(user.id)}"}


def _cookies(response) -> dict[str, SimpleCookie]:
    jar: dict[str, SimpleCookie] = {}
    for header in response.headers.get_list("set-cookie"):
        cookie = SimpleCookie()
        cookie.load(header)
        for name in cookie:
            jar[name] = cookie
    return jar


def _cookie_header(response) -> str:
    return "; ".join(f"{name}={jar[name].value}" for name, jar in _cookies(response).items() if jar[name].value)


async def _paired_phone(client, db, username: str = "mobile-owner"):
    """A user, their Mac login headers and a fully paired phone's cookies."""
    user = await user_named(db, username)
    mac = await _mac_headers(db, user)
    created = await client.post(PAIRINGS, headers=mac)
    assert created.status_code == 201, created.text
    code = created.json()["url"].split("#c=", 1)[1]
    scanned = await client.post("/api/v1/mobile/pairings/scan", json={"code": code},
                                headers={"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X)"})
    assert scanned.status_code == 200, scanned.text
    pairing_id, secret = scanned.json()["pairing_id"], scanned.json()["scan_secret"]
    confirmed = await client.post(CONFIRM.format(pairing_id), json={"approve": True}, headers=_browser(user))
    assert confirmed.status_code == 200, confirmed.text
    status = await client.post(f"/api/v1/mobile/pairings/{pairing_id}/status", json={"scan_secret": secret})
    claimed = await client.post("/api/v1/mobile/claim", json={"claim": status.json()["claim"]})
    assert claimed.status_code == 201, claimed.text
    client.cookies.clear()  # the phone's cookies travel explicitly; the shared client stays the admin's browser
    return user, mac, claimed
