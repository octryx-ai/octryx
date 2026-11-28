"""Contract: only an admin changes tool configs, and a kept secret never silently follows a new host."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog, BuiltInToolConfig, Role, SavedPythonScript, StoredSecret, User, UserRole
from app.services.auth.tokens import create_access_token, hash_password
from app.services.tool_config.secret_rebind import AUDIT_ACTION_CONFIRMED, AUDIT_ACTION_REFUSED

WIKI_A = "https://wiki-a.example.test/wiki"
WIKI_B = "https://wiki-b.example.test/wiki"


async def _viewer(db) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=str(uuid.uuid4()),
        username=f"viewer-{suffix}",
        email=f"viewer-{suffix}@example.com",
        password_hash=hash_password("viewer-Test-Pw-123"),
        display_name="viewer",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    viewer_role = (await db.execute(select(Role).where(Role.name == "viewer"))).scalar_one()
    db.add(UserRole(user_id=user.id, role_id=viewer_role.id))
    await db.commit()
    return user


def _confluence_form(url: str, **extra: str) -> dict[str, str]:
    return {
        "tool_name": "confluence",
        "project_id": "",
        "config_json": json.dumps({"confluence_url": url, "confluence_auth_mode": "basic",
                                   "confluence_username": "sync-bot"}),
        "is_active": "true",
        **extra,
    }


async def _global_confluence(db) -> BuiltInToolConfig | None:
    await db.rollback()
    return (
        await db.execute(
            select(BuiltInToolConfig).where(
                BuiltInToolConfig.tool_name == "confluence", BuiltInToolConfig.project_id.is_(None)
            )
        )
    ).scalar_one_or_none()


async def _audit_rows(db, action: str) -> list[AuditLog]:
    await db.rollback()
    return list((await db.execute(select(AuditLog).where(AuditLog.action == action))).scalars().all())


@pytest.mark.asyncio
async def test_a_viewer_is_refused_on_every_tools_route_and_nothing_is_written(client, db):
    viewer = await _viewer(db)
    client.cookies.set("access_token", create_access_token(viewer.id))

    page = await client.get("/admin/tools")
    assert page.status_code == 403
    assert page.json()["detail"] == "Admin role required"
    saved = await client.post("/admin/tools/configs/save", data=_confluence_form(WIKI_A, confluence_password="pw-1"))
    assert saved.status_code == 403
    assert saved.json()["detail"] == "Admin role required"
    tested = await client.post("/admin/tools/configs/test", data=_confluence_form(WIKI_A))
    assert tested.status_code == 403
    script = await client.post(
        "/admin/tools/scripts/save",
        data={"name": "viewer_script", "purpose": "p", "code": "def main(args):\n    return {}\n", "is_active": "true"},
    )
    assert script.status_code == 403
    assert (await client.post("/admin/tools/scripts/delete/any-id")).status_code == 403

    assert await _global_confluence(db) is None
    assert (await db.execute(select(StoredSecret).where(StoredSecret.tool_name == "confluence"))).first() is None
    assert (
        await db.execute(select(SavedPythonScript).where(SavedPythonScript.name == "viewer_script"))
    ).first() is None


@pytest.mark.asyncio
async def test_an_admin_saves_and_a_host_change_without_the_secret_is_refused(admin_client, db, monkeypatch):
    first = await admin_client.post("/admin/tools/configs/save", data=_confluence_form(WIKI_A, confluence_password="pw-1"))
    assert first.status_code == 303
    stored = await _global_confluence(db)
    secret_ref = stored.config["confluence_password_secret_ref"]
    assert stored.config["confluence_url"] == WIKI_A

    same_host = await admin_client.post("/admin/tools/configs/save", data=_confluence_form(f"{WIKI_A}/v2"))
    assert same_host.status_code == 303

    async def _never_called(tool_name, config):
        raise AssertionError("the stored secret must not reach a changed host")

    monkeypatch.setattr("app.web.routers.tools_scripts.run_connector_connection_test", _never_called)
    for route in ("/admin/tools/configs/save", "/admin/tools/configs/test"):
        refused = await admin_client.post(route, data=_confluence_form(WIKI_B))
        assert refused.status_code == 409
        detail = refused.json()["detail"]
        assert detail["state"] == "secret_rebind_required"
        assert detail["changed_target_fields"] == ["confluence_url"]
        assert detail["kept_fields"] == ["confluence_password"]
    unchanged = await _global_confluence(db)
    assert unchanged.config["confluence_url"] == f"{WIKI_A}/v2"
    assert unchanged.config["confluence_password_secret_ref"] == secret_ref

    refusals = await _audit_rows(db, AUDIT_ACTION_REFUSED)
    assert len(refusals) == 2
    audit_text = json.dumps([row.details for row in refusals])
    assert refusals[0].details["changed_target_fields"] == ["confluence_url"]
    assert refusals[0].details["kept_fields"] == ["confluence_password"]
    assert "wiki-b" not in audit_text and "wiki-a" not in audit_text and "pw-1" not in audit_text

    reentered = await admin_client.post(
        "/admin/tools/configs/save", data=_confluence_form(WIKI_B, confluence_password="pw-2")
    )
    assert reentered.status_code == 303
    assert (await _global_confluence(db)).config["confluence_url"] == WIKI_B

    confirmed = await admin_client.post(
        "/admin/tools/configs/save", data=_confluence_form(WIKI_A, confirm_secret_rebind="true")
    )
    assert confirmed.status_code == 303
    assert (await _global_confluence(db)).config["confluence_url"] == WIKI_A
    assert len(await _audit_rows(db, AUDIT_ACTION_CONFIRMED)) == 1


@pytest.mark.asyncio
async def test_the_admin_connector_json_save_refuses_a_host_change_without_the_secret(admin_client, db):
    route = "/admin/chat/api/panel/connectors/confluence"
    first = await admin_client.put(route, json={"confluence_url": WIKI_A, "confluence_auth_mode": "basic",
                                       "confluence_username": "sync-bot", "confluence_password": "pw-1",
                                       "is_active": True})
    assert first.status_code == 200

    refused = await admin_client.put(route, json={"confluence_url": WIKI_B, "is_active": True})
    assert refused.status_code == 409
    assert refused.json()["detail"]["state"] == "secret_rebind_required"
    assert (await _global_confluence(db)).config["confluence_url"] == WIKI_A

    confirmed = await admin_client.put(route, json={"confluence_url": WIKI_B, "confirm_secret_rebind": True})
    assert confirmed.status_code == 200
    assert (await _global_confluence(db)).config["confluence_url"] == WIKI_B

    assert (await admin_client.delete(route)).json()["detail"]["code"] == "connector_confirmation_mismatch"
    assert (await admin_client.delete(route, params={"confirm_name": "confluence"})).status_code == 200
    fresh = await admin_client.put(route, json={"confluence_url": WIKI_A, "is_active": True})
    assert fresh.status_code == 200
    assert "confluence_password_secret_ref" not in (await _global_confluence(db)).config
