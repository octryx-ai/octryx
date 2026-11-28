"""The running application refuses cross-site and deactivated-admin panel mutations before writing anything, while same-origin and bearer clients still work."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.models import AuditLog, FeatureFlag, User
from app.panel_csrf_policy import CSRF_REJECTION_DETAIL
from app.web._helpers.cookie_principal import INACTIVE_PRINCIPAL_DETAIL
from tests.conftest import ADMIN_PASSWORD, HARNESS_ORIGIN, send_without_origin
from tests.support.panel_cookie_mutation_support import FOREIGN_ORIGIN, PANEL_PATH


async def login(client) -> None:
    response = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert response.status_code == 303


async def flag_keys(db) -> set[str]:
    return set((await db.execute(select(FeatureFlag.key))).scalars().all())


@pytest.mark.asyncio
async def test_the_harness_models_the_browser_it_stands_in_for(client):
    assert client.headers["origin"] == HARNESS_ORIGIN == str(client.base_url)


@pytest.mark.asyncio
async def test_the_admin_ui_same_origin_mutation_still_works(client, db):
    await login(client)
    response = await client.post(PANEL_PATH, json={"key": "panel-csrf-allowed", "enabled": True})
    assert response.status_code == 200
    assert "panel-csrf-allowed" in await flag_keys(db)


@pytest.mark.asyncio
async def test_a_foreign_origin_cookie_mutation_writes_nothing(client, db):
    await login(client)
    response = await client.post(
        PANEL_PATH,
        json={"key": "panel-csrf-foreign", "enabled": True},
        headers={"Origin": FOREIGN_ORIGIN},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == CSRF_REJECTION_DETAIL
    assert "panel-csrf-foreign" not in await flag_keys(db)


@pytest.mark.asyncio
async def test_a_cookie_mutation_without_an_origin_writes_nothing(client, db):
    await login(client)
    response = await send_without_origin(
        client, "POST", PANEL_PATH, json={"key": "panel-csrf-no-origin", "enabled": True}
    )
    assert response.status_code == 403
    assert "panel-csrf-no-origin" not in await flag_keys(db)


@pytest.mark.asyncio
async def test_the_refusal_is_identical_for_an_existing_and_an_unknown_resource(client, db):
    await login(client)
    created = await client.post(PANEL_PATH, json={"key": "panel-csrf-existing", "enabled": True})
    assert created.status_code == 200

    existing = await client.delete(
        f"{PANEL_PATH}/panel-csrf-existing", headers={"Origin": FOREIGN_ORIGIN}
    )
    unknown = await client.delete(
        f"{PANEL_PATH}/panel-csrf-does-not-exist", headers={"Origin": FOREIGN_ORIGIN}
    )
    assert existing.status_code == unknown.status_code == 403

    # Everything but the per-request correlation id is byte-identical, and that
    # id is the one the response header carries for every request on this
    # application, refused or not — it distinguishes requests, not resources.
    def without_request_id(response):
        payload = json.loads(response.text)
        assert payload.pop("request_id") == response.headers["X-Request-ID"]
        return payload

    assert without_request_id(existing) == without_request_id(unknown)
    assert "panel-csrf-existing" in await flag_keys(db)


@pytest.mark.asyncio
async def test_a_bearer_panel_mutation_needs_no_origin(client, db):
    token_response = await client.post(
        "/api/v1/auth/login", data={"username": "admin", "password": ADMIN_PASSWORD}
    )
    assert token_response.status_code == 200
    response = await send_without_origin(
        client,
        "POST",
        PANEL_PATH,
        json={"key": "panel-csrf-bearer", "enabled": True},
        headers={"Authorization": f"Bearer {token_response.json()['access_token']}"},
    )
    assert response.status_code == 200
    assert "panel-csrf-bearer" in await flag_keys(db)


@pytest.mark.asyncio
async def test_a_fake_bearer_header_does_not_let_a_cross_site_cookie_mutation_through(client, db):
    await login(client)
    for header in ({"Authorization": "Bearer attacker-supplied-value"}, {"X-API-Key": "attacker-value"}):
        refused = await client.post(
            PANEL_PATH,
            json={"key": "panel-csrf-fake-header", "enabled": True},
            headers={**header, "Origin": FOREIGN_ORIGIN},
        )
        assert refused.status_code == 403
        origin_less = await send_without_origin(
            client,
            "POST",
            PANEL_PATH,
            json={"key": "panel-csrf-fake-header", "enabled": True},
            headers=header,
        )
        assert origin_less.status_code == 403
    assert "panel-csrf-fake-header" not in await flag_keys(db)


@pytest.mark.asyncio
async def test_a_deactivated_admin_is_refused_before_the_mutation(client, db):
    await login(client)
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    admin.is_active = False
    await db.flush()

    response = await client.post(PANEL_PATH, json={"key": "panel-csrf-inactive", "enabled": True})
    assert response.status_code == 401
    assert response.json()["detail"] == INACTIVE_PRINCIPAL_DETAIL
    assert "panel-csrf-inactive" not in await flag_keys(db)


@pytest.mark.asyncio
async def test_the_refused_principal_is_never_attributed_anything_before_the_401(client, db):
    await login(client)
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    admin.is_active = False
    await db.flush()
    before = set((await db.execute(select(AuditLog.id))).scalars().all())

    response = await client.post(PANEL_PATH, json={"key": "panel-csrf-no-attribution", "enabled": True})
    assert response.status_code == 401

    added = [
        row
        for row in (await db.execute(select(AuditLog))).scalars().all()
        if row.id not in before
    ]
    assert [row.action for row in added if row.action.startswith("auth.")] == []
    for row in added:
        # Nothing claims the mutation happened, and nothing puts the deactivated
        # account's id on a row that reads like work it did.
        assert (row.details or {}).get("status_code") == 401
        assert row.user_id != admin.id
    assert "panel-csrf-no-attribution" not in await flag_keys(db)


@pytest.mark.asyncio
async def test_a_deactivated_admin_is_refused_on_a_permission_scoped_route_too(client, db):
    await login(client)
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    admin.is_active = False
    await db.flush()

    # panel_users routes authorize by permission rather than by the admin role;
    # the refusal must still be the 401 of the principal guard, not a 403 from
    # an authorization check that already saw the deactivated principal.
    response = await client.post(
        "/admin/chat/api/panel/identity-groups", json={"name": "panel-csrf-inactive-group"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == INACTIVE_PRINCIPAL_DETAIL


@pytest.mark.asyncio
async def test_the_login_page_surface_redirects_a_deactivated_principal(client, db):
    await login(client)
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    admin.is_active = False
    await db.flush()

    response = await client.get("/chat", follow_redirects=False)
    assert response.status_code in (302, 303, 307)
    assert response.headers["location"].endswith("/chat/login")
