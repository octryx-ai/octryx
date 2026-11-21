"""Phone token scope: the phone sees only its own usage and phone surfaces, and its tokens are never web access tokens."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.devices.device_support import user_named
from tests.mobile.mobile_pairing_support import _cookie_header, _paired_phone


@pytest.mark.asyncio
async def test_usage_is_the_users_own_and_only_in_their_workspaces(client, db):
    from app.models import UserProject
    from tests.knowledge_evidence_seed_support import seed_workspace

    user, _mac, claimed = await _paired_phone(client, db)
    workspace_id = await seed_workspace(db)
    db.add(UserProject(user_id=user.id, project_id=workspace_id, role="member"))
    await db.flush()
    cookie = _cookie_header(claimed)
    usage = await client.get(f"/api/v1/mobile/usage?workspace_id={workspace_id}", headers={"cookie": cookie})
    assert usage.status_code == 200, usage.text
    assert set(usage.json()) == {"state", "reason", "workspace_id", "limit_usd", "spent_usd", "resets_at",
                                 "seat_allowance", "codex_seat_allowance"}
    foreign = await client.get("/api/v1/mobile/usage?workspace_id=not-mine", headers={"cookie": cookie})
    assert foreign.status_code == 404


# --- the phone's token reaches only the phone app's surfaces --------------------------------------------------


@pytest.mark.asyncio
async def test_a_phone_token_reaches_only_the_phone_surfaces(client, db, auth_headers):
    from app.models import Role, UserRole

    user, _mac, claimed = await _paired_phone(client, db)
    admin_role = (await db.execute(select(Role).where(Role.name == "admin"))).scalar_one()
    db.add(UserRole(user_id=user.id, role_id=admin_role.id))  # even an admin's phone is no admin surface
    await db.flush()
    cookie = {"cookie": _cookie_header(claimed)}
    assert (await client.get("/api/v1/devices", headers=cookie)).status_code == 200
    assert (await client.get("/api/v1/mobile/devices", headers=cookie)).status_code == 200
    for path in ("/api/v1/admin/devices/login-validity", "/api/v1/auth/me", "/api/v1/sessions"):
        assert (await client.get(path, headers=cookie)).status_code == 401, path


@pytest.mark.asyncio
async def test_a_session_stream_token_is_never_a_web_access_token(client, db):
    from fastapi import HTTPException

    from app.services.auth.service import decode_token
    from app.services.auth.tokens import create_session_stream_token

    user = await user_named(db, "stream-user")
    token = create_session_stream_token(user_id=user.id, session_id="s-1")
    with pytest.raises(HTTPException):
        decode_token(token)
    assert (await client.get("/api/v1/devices", headers={"Authorization": f"Bearer {token}"})).status_code == 401


@pytest.mark.asyncio
async def test_only_callers_that_check_the_phone_accept_its_token(client, db):
    from fastapi import HTTPException

    from app.services.auth.service import decode_token
    from app.services.auth.tokens import verify_ws_token
    from app.services.mobile.session import mint_mobile_access_token

    user = await user_named(db, "phone-user")
    token = mint_mobile_access_token(user_id=user.id, device_id="mob_x")
    with pytest.raises(HTTPException):
        decode_token(token)  # WebSockets, OAuth consent, the board: never a phone
    assert decode_token(token, allow_phone=True) == user.id
    from app.exceptions.api import AuthenticationError

    with pytest.raises(AuthenticationError):
        await verify_ws_token(token)
    from starlette.requests import Request

    from app.web._helpers.auth import _get_user_from_cookie

    request = Request({"type": "http", "method": "GET", "path": "/oauth/authorize", "headers": [
        (b"cookie", f"access_token={token}".encode())], "query_string": b""})
    assert _get_user_from_cookie(request) is None
