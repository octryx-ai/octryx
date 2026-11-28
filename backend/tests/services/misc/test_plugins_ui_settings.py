"""Plugin pages, settings and bridge: the UI is served only with its own short-lived token and strict headers, settings keep secrets in the secret store, the bridge runs only declared methods, and the phone never switches plugins or changes settings."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.services.plugins.package import files_from_folder, read_package
from tests.policy_engine_support import bearer
from tests.support.plugins_support import SHIPPED, _in_image, _switch, _workspace_admin, uid


async def _install(client, db, folder: Path, user_id: str, workspace_id: str, files: dict[str, bytes]) -> dict:
    package = read_package(files)
    await _in_image(db, folder, {package.manifest.id: files})
    done = await _switch(client, user_id, package.manifest.id, workspace_id)
    assert done.status_code == 200, done.text
    return done.json()


@pytest.mark.asyncio
async def test_the_plugin_ui_is_served_only_with_its_own_short_lived_token_and_strict_headers(client, db, tmp_path):
    user, ours, _ = await _workspace_admin(db)
    user_id, ours_id = user.id, ours.id
    body = await _install(client, db, tmp_path, user_id, ours_id, files_from_folder(SHIPPED))
    ui = (await client.get(f"/api/v1/plugins/{body['id']}/ui", headers=bearer(user_id))).json()
    assert ui["slots"]["pages"][0]["where"] == "work" and "search_jira_tickets" in ui["methods"]

    page = await client.get(ui["base_url"] + "index.html")
    assert page.status_code == 200 and b'src="app.js"' in page.content
    assert "connect-src 'none'" in page.headers["content-security-policy"]
    assert "frame-ancestors 'self'" in page.headers["content-security-policy"]
    assert page.headers["referrer-policy"] == "no-referrer"
    token = ui["base_url"].rstrip("/").rsplit("/", 1)[1]
    assert (await client.get(f"/plugin-ui/{uid()}/{token}/index.html")).status_code == 404
    assert (await client.get("/api/v1/plugins", params={"workspace_id": ours_id},
                             headers={"Authorization": f"Bearer {token}"})).status_code == 401

    from datetime import timedelta

    from app.services.plugins import ui as plugin_ui

    old = plugin_ui.TOKEN_LIFETIME
    plugin_ui.TOKEN_LIFETIME = timedelta(seconds=-1)
    try:
        expired = plugin_ui.issue_token(body["id"], user_id)
    finally:
        plugin_ui.TOKEN_LIFETIME = old
    late = await client.get(f"/plugin-ui/{body['id']}/{expired}/index.html")
    assert late.status_code == 401 and late.json()["detail"]["code"] == "plugin_ui_token_expired"
    assert plugin_ui.masked_path(f"/plugin-ui/{body['id']}/{token}/app.js") == f"/plugin-ui/{body['id']}/***/app.js"

    await client.post(f"/api/v1/plugins/{body['id']}/disable", headers=bearer(user_id))
    assert (await client.get(f"/api/v1/plugins/{body['id']}/ui", headers=bearer(user_id))).json()["detail"][
        "code"] == "plugin_disabled"
    assert (await client.get(ui["base_url"] + "index.html")).status_code == 404


@pytest.mark.asyncio
async def test_settings_keep_secrets_in_the_secret_store_and_the_bridge_runs_only_declared_methods(client, db,
                                                                                                 tmp_path):
    user, ours, _ = await _workspace_admin(db)
    user_id, ours_id = user.id, ours.id
    package = {
        "octryx-plugin.yaml": b"""
apiVersion: octryx.ai/plugin/v1
id: acme.status-board
name: Status board
version: 0.1.0
publisher: ACME
contributes:
  ui:
    bundle: ui
    tiles: [{id: board, title: Board, on: workspace}]
    methods: [settings.get, search_jira_tickets, edit_workspace_file]
permissions:
  connections: [jira]
settings: settings.schema.json
""",
        "settings.schema.json": b'{"type": "object", "required": ["team"], "properties": {'
                                b'"team": {"type": "string"}, "limit": {"type": "integer"},'
                                b'"api_key": {"type": "string", "format": "password"}}}',
        "ui/index.html": b"<!doctype html><p>board</p>",
    }
    body = await _install(client, db, tmp_path, user_id, ours_id, package)
    base = f"/api/v1/plugins/{body['id']}"

    async def needs() -> list[bool]:
        listed = (await client.get("/api/v1/plugins/available", params={"workspace_id": ours_id},
                                   headers=bearer(user_id))).json()["plugins"]
        return [p["needs_settings"] for p in listed]

    assert await needs() == [True]

    missing = await client.put(f"{base}/settings", json={"values": {"limit": 5}}, headers=bearer(user_id))
    assert missing.json()["detail"]["code"] == "plugin_setting_required"
    wrong = await client.put(f"{base}/settings", json={"values": {"team": "a", "limit": "x"}}, headers=bearer(user_id))
    assert wrong.json()["detail"]["code"] == "plugin_setting_invalid"
    saved = await client.put(f"{base}/settings", json={"values": {"team": "Core", "limit": 5, "api_key": "s3cr3t"}},
                             headers=bearer(user_id))
    assert saved.json()["values"] == {"team": "Core", "limit": 5, "api_key": {"set": True}}
    assert await needs() == [False]
    kept = await client.put(f"{base}/settings", json={"values": {"limit": 7}}, headers=bearer(user_id))
    assert kept.json()["values"]["api_key"] == {"set": True}
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "plugins.settings_saved"))).scalars().all()
    assert audit and all("s3cr3t" not in str(row.details) for row in audit)

    def call(method: str, **params):
        return client.post(f"{base}/bridge", json={"method": method, "params": params}, headers=bearer(user_id))

    assert (await call("settings.get")).json() == {"result": {"team": "Core", "limit": 7}}
    refused = await call("create_confluence_page", space_key="X", title="Y")
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "plugin_method_not_declared"
    jira = await call("search_jira_tickets", query="release")
    assert jira.status_code == 200 and ("error" in jira.json() or "result" in jira.json())
    change = await call("edit_workspace_file", path="notes.md", old_text="a", new_text="b")
    assert "capability" in change.json()["error"]["message"].lower(), change.text
    calls = (await db.execute(select(AuditLog).where(AuditLog.action == "plugins.bridge_call"))).scalars().all()
    assert {row.details["method"] for row in calls} == {"settings.get", "search_jira_tickets", "edit_workspace_file"}


def test_the_phone_reaches_plugin_pages_but_never_switches_plugins_or_changes_settings():
    from app.services.mobile.session import phone_may_use

    allowed = [("GET", "/api/v1/plugins"), ("GET", "/api/v1/plugins/i1/ui"), ("POST", "/api/v1/plugins/i1/bridge"),
               ("GET", "/api/v1/approvals/a1")]
    refused = [("POST", "/api/v1/plugins/available/p/activate"), ("POST", "/api/v1/plugins/available/p/deactivate"),
               ("POST", "/api/v1/plugins/i1/disable"), ("PUT", "/api/v1/plugins/i1/settings"),
               ("GET", "/api/v1/plugins/i1/settings"), ("POST", "/api/v1/approvals/a1/always"),
               ("GET", "/api/v1/approvals/a1/extra")]
    assert all(phone_may_use(method, path) for method, path in allowed)
    assert not any(phone_may_use(method, path) for method, path in refused)
