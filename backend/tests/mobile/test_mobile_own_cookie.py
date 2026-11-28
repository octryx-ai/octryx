"""The phone's own access cookie ``octryx_phone_access``: one browser holds the web login and ``/m`` at once, and
signing out on the phone leaves the web login alone."""

from __future__ import annotations

import pytest

from app.auth_cookie_policy import ACCESS_TOKEN_COOKIE, PHONE_ACCESS_COOKIE
from app.services.auth import create_access_token
from app.services.mobile.contract import MOBILE_COOKIE
from tests.mobile.mobile_pairing_support import _cookies, _paired_phone


def _phone_jar(response) -> dict[str, str]:
    return {name: jar[name].value for name, jar in _cookies(response).items() if jar[name].value}


def _header(cookies: dict[str, str]) -> dict[str, str]:
    return {"cookie": "; ".join(f"{name}={value}" for name, value in cookies.items())}


def _deleted(response) -> set[str]:
    return {name for name, jar in _cookies(response).items() if not jar[name].value or jar[name]["max-age"] == "0"}


@pytest.mark.asyncio
async def test_a_browser_keeps_the_web_login_and_the_phone_session(client, db):
    user, _mac, claimed = await _paired_phone(client, db)
    phone = _phone_jar(claimed)
    assert set(phone) == {MOBILE_COOKIE, PHONE_ACCESS_COOKIE}
    browser = {ACCESS_TOKEN_COOKIE: create_access_token(user.id), **phone}

    refreshed = await client.post("/api/v1/mobile/session", headers=_header(browser))
    assert refreshed.status_code == 200, refreshed.text
    assert set(_phone_jar(refreshed)) == {PHONE_ACCESS_COOKIE} and ACCESS_TOKEN_COOKIE not in _cookies(refreshed)
    browser.update(_phone_jar(refreshed))

    me = await client.get("/api/v1/auth/me", headers=_header(browser))
    assert me.status_code == 200 and me.json()["id"] == user.id
    page = await client.get("/chat", headers=_header(browser), follow_redirects=False)
    assert page.status_code not in (303, 307), page.headers.get("location")
    phones = await client.get("/api/v1/mobile/devices", headers=_header(browser))
    assert phones.status_code == 200 and phones.json()["items"][0]["this_device"]
    assert (await client.get("/api/v1/mobile/local-sessions", headers=_header(browser))).status_code == 200
    assert (await client.get("/api/v1/mobile/live", headers=_header(browser))).status_code == 200


@pytest.mark.asyncio
async def test_signing_out_on_the_phone_leaves_the_web_login(client, db):
    user, _mac, claimed = await _paired_phone(client, db)
    browser = {ACCESS_TOKEN_COOKIE: create_access_token(user.id), **_phone_jar(claimed)}

    out = await client.post("/api/v1/mobile/logout", headers=_header(browser))
    assert out.status_code == 200 and out.json()["state"] == "signed_out"
    assert _deleted(out) == {MOBILE_COOKIE, PHONE_ACCESS_COOKIE}
    assert ACCESS_TOKEN_COOKIE not in _cookies(out)
    web = {ACCESS_TOKEN_COOKIE: browser[ACCESS_TOKEN_COOKIE]}
    assert (await client.get("/api/v1/auth/me", headers=_header(web))).status_code == 200
    phone_only = {PHONE_ACCESS_COOKIE: browser[PHONE_ACCESS_COOKIE]}
    assert (await client.get("/api/v1/mobile/devices", headers=_header(phone_only))).status_code == 401
    refused = await client.post("/api/v1/mobile/session", headers=_header(browser))
    assert refused.status_code == 401 and ACCESS_TOKEN_COOKIE not in _cookies(refused)


@pytest.mark.asyncio
async def test_a_web_token_under_the_phone_cookie_name_is_refused(client, db):
    user, _mac, _claimed = await _paired_phone(client, db)
    disguised = {PHONE_ACCESS_COOKIE: create_access_token(user.id)}
    for path in ("/api/v1/auth/me", "/api/v1/devices", "/api/v1/mobile/devices", "/chat/api/bootstrap"):
        assert (await client.get(path, headers=_header(disguised))).status_code == 401, path
    page = await client.get("/chat", headers=_header(disguised), follow_redirects=False)
    assert page.status_code == 303 and page.headers["location"] == "/chat/login"


@pytest.mark.asyncio
async def test_the_phone_cookie_reaches_only_the_phone_surfaces(client, db):
    _user, _mac, claimed = await _paired_phone(client, db)
    phone = {PHONE_ACCESS_COOKIE: _phone_jar(claimed)[PHONE_ACCESS_COOKIE]}
    assert (await client.get("/api/v1/devices", headers=_header(phone))).status_code == 200
    assert (await client.get("/chat/api/bootstrap", headers=_header(phone))).status_code == 200
    assert (await client.get("/chat/api/workflows", headers=_header(phone))).status_code == 200
    for path in ("/api/v1/auth/me", "/api/v1/sessions", "/api/v1/admin/devices/login-validity"):
        assert (await client.get(path, headers=_header(phone))).status_code == 401, path
    page = await client.get("/chat", headers=_header(phone), follow_redirects=False)
    assert page.status_code == 303 and page.headers["location"] == "/chat/login"
    broken = {ACCESS_TOKEN_COOKIE: "not-a-token", **phone}
    assert (await client.get("/api/v1/devices", headers=_header(broken))).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=_header(broken))).status_code == 401


@pytest.mark.asyncio
async def test_interactive_routes_take_either_cookie_but_never_a_key_or_a_bearer(client, db):
    user, _mac, claimed = await _paired_phone(client, db)
    phone = _header({PHONE_ACCESS_COOKIE: _phone_jar(claimed)[PHONE_ACCESS_COOKIE]})
    web = _header({ACCESS_TOKEN_COOKIE: create_access_token(user.id)})
    bearer = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    for path in ("/api/v1/mobile/local-sessions", "/api/v1/mobile/live"):
        assert (await client.get(path, headers=phone)).status_code == 200, path
        assert (await client.get(path, headers=web)).status_code == 200, path
        for extra in (bearer, {"X-API-Key": "oek_not-a-key"}):
            refused = await client.get(path, headers={**phone, **extra})
            assert refused.status_code in (401, 403), (path, extra.keys())
        assert (await client.get(path, headers=bearer)).status_code == 403, path


def test_the_rate_limiter_and_the_panel_guard_know_the_phone_cookie():
    from starlette.requests import Request

    from app.middleware.security.rate_limit_identity import request_principal
    from app.panel_csrf_policy import PANEL_AUTH_COOKIES
    from app.services.mobile.session import mint_mobile_access_token

    def request(cookie: str) -> Request:
        return Request({"type": "http", "method": "GET", "path": "/api/v1/devices", "query_string": b"",
                        "headers": [(b"cookie", cookie.encode())]})

    phone = mint_mobile_access_token(user_id="u-phone", device_id="mob_x")
    assert request_principal(request(f"{PHONE_ACCESS_COOKIE}={phone}")) == "user:u-phone"
    web = create_access_token("u-web")
    assert request_principal(request(f"{ACCESS_TOKEN_COOKIE}={web}; {PHONE_ACCESS_COOKIE}={phone}")) == "user:u-web"
    assert request_principal(request(f"{PHONE_ACCESS_COOKIE}={web}")) is None
    assert PHONE_ACCESS_COOKIE in PANEL_AUTH_COOKIES  # a cookie-authenticated panel mutation needs its origin
