"""Contract: the Workspace connection never leaks, re-validates or mixes.

Through the real admin panel routes with two loopback stubs (A: the saved target, B: another one),
reached through the pinned egress transport and the acceptance loopback exemption:

- a connection test whose request moves the target never sends a stored secret there (409 and an
  audit row, unless the secret is re-entered or the rebind confirmed), for Confluence and Jira, on the
  Workspace test, the ``/admin/tools`` test and the global card test; a Workspace test that
  sets its own target never inherits the global secret either;
- an access save validates only what it changes (an entry the connection save would now refuse keeps saving
  access); an invalid limit is a coded 422;
- a Workspace test records its health but never feeds the global circuit breaker;
- a mode switch leaves one credential unit (the previous mode's principal and secret ref go);
- a disabled global entry is ``configured: true, active: false``.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import uuid

from sqlalchemy import select

from app.models import AuditLog, BuiltInToolConfig, Project
from app.services.circuit_breaker import list_circuit_breakers
from app.services.connector_health import list_connector_health_rows
from tests.conftest import ADMIN_PASSWORD
from tests.egress_support import stub_settings, use_stub_settings
from tests.test_workspace_connector_connection import BASIC, PASSWORD, USER, _own, _stub

PANEL = "/admin/chat/api/panel"
JIRA_TOKEN = "jira-saved-token"


async def _login(client) -> None:
    response = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert response.status_code == 303


async def _project(db) -> str:
    project = Project(name=f"conn-r-{uuid.uuid4().hex[:8]}")
    db.add(project)
    await db.commit()
    return project.id


@contextlib.asynccontextmanager
async def _two_stubs(monkeypatch):
    async with _stub() as (base_a, seen_a), _stub() as (base_b, seen_b):
        hosts = ",".join(base.removeprefix("http://") for base in (base_a, base_b))
        use_stub_settings(monkeypatch, stub_settings(hosts=hosts))
        yield base_a, seen_a, base_b, seen_b


async def _config(db, project_id: str, tool: str = "confluence") -> dict:
    entry = (await db.execute(select(BuiltInToolConfig).where(
        BuiltInToolConfig.tool_name == tool, BuiltInToolConfig.project_id == project_id))).scalar_one()
    await db.refresh(entry)
    return dict(entry.config or {})


async def _refusals(db) -> int:
    rows = await db.execute(select(AuditLog).where(AuditLog.action == "tool_config.secret_rebind_refused"))
    return len(rows.scalars().all())


async def test_r1_a_workspace_test_never_sends_the_stored_secret_to_a_changed_target(client, db, monkeypatch):
    await _login(client)
    project_id = await _project(db)
    url = f"{PANEL}/projects/{project_id}/connectors/confluence/connection"
    async with _two_stubs(monkeypatch) as (base_a, seen_a, base_b, seen_b):
        assert (await client.put(url, json=_own(base_a, confluence_password=PASSWORD))).status_code == 200
        before = await _refusals(db)

        moved = await client.post(f"{url}/test", json=_own(base_b))
        assert moved.status_code == 409 and moved.json()["detail"]["state"] == "secret_rebind_required"
        assert seen_b == [] and await _refusals(db) == before + 1

        typed = await client.post(f"{url}/test", json=_own(base_b, confluence_password="typed-for-b"))
        assert typed.status_code == 200 and BASIC not in seen_b, "only the re-entered secret goes to B"
        assert (await client.post(f"{url}/test", json=_own(base_a))).json()["ok"] is True
        assert seen_a[-1] == BASIC, "the saved target still gets the saved secret"

        confirmed = await client.post(f"{url}/test", json={**_own(base_b), "confirm_secret_rebind": True})
        assert confirmed.status_code == 200 and seen_b[-1] == BASIC, "only an explicit confirm moves it"


async def test_r1_jira_and_the_global_secret_follow_the_same_rule(client, db, monkeypatch):
    await _login(client)
    project_id = await _project(db)
    jira = f"{PANEL}/projects/{project_id}/connectors/jira/connection"
    confluence = f"{PANEL}/projects/{project_id}/connectors/confluence/connection"
    bearer = f"Bearer {JIRA_TOKEN}"
    async with _two_stubs(monkeypatch) as (base_a, _seen_a, base_b, seen_b):
        saved = await client.put(jira, json={"source": "workspace", "jira_url": base_a,
                                             "jira_auth_mode": "bearer_pat", "jira_token": JIRA_TOKEN})
        assert saved.status_code == 200, saved.text
        moved = await client.post(f"{jira}/test", json={"source": "workspace", "jira_url": base_b,
                                                       "jira_auth_mode": "bearer_pat"})
        assert moved.status_code == 409 and bearer not in seen_b and seen_b == []

        # The Workspace uses the global connection; a test with its own target never inherits the global secret.
        global_saved = await client.put(f"{PANEL}/connectors/confluence", json={
            "confluence_url": base_a, "confluence_auth_mode": "basic", "confluence_username": USER,
            "confluence_password": PASSWORD})
        assert global_saved.status_code == 200, global_saved.text
        await client.post(f"{confluence}/test", json=_own(base_b))
        assert BASIC not in seen_b


async def test_r1_the_legacy_and_global_card_tests_never_move_a_stored_secret(client, db, monkeypatch):
    await _login(client)
    project_id = await _project(db)
    url = f"{PANEL}/projects/{project_id}/connectors/confluence/connection"
    async with _two_stubs(monkeypatch) as (base_a, seen_a, base_b, seen_b):
        assert (await client.put(url, json=_own(base_a, confluence_password=PASSWORD))).status_code == 200
        legacy = await client.post("/admin/tools/configs/test", data={
            "tool_name": "confluence", "project_id": project_id,
            "config_json": f'{{"confluence_url": "{base_b}", "confluence_auth_mode": "basic", '
                           f'"confluence_username": "{USER}"}}',
        })
        assert legacy.status_code == 409 and seen_b == []

        assert (await client.put(f"{PANEL}/connectors/confluence", json={
            "confluence_url": base_a, "confluence_auth_mode": "basic", "confluence_username": USER,
            "confluence_password": PASSWORD})).status_code == 200
        # The global card test reads no request body: it only ever tests the saved global connection.
        card = await client.post(f"{PANEL}/connectors/confluence/test", json={"confluence_url": base_b})
        assert card.json()["ok"] is True and seen_b == [] and seen_a[-1] == BASIC


async def test_r2_access_save_validates_only_what_it_changes(client, db):
    await _login(client)
    project_id = await _project(db)
    # A stored bare Cloud URL the connection save refuses.
    db.add(BuiltInToolConfig(tool_name="confluence", project_id=project_id, is_active=True, config={
        "confluence_url": "https://your-site.atlassian.net", "confluence_username": USER}))
    await db.commit()
    url = f"{PANEL}/projects/{project_id}/connectors/confluence"
    saved = await client.put(url, json={"is_active": False, "limits": {
        "confluence_allowed_spaces": [{"space_key": "ENG", "enabled": True}]}})
    assert saved.status_code == 200, saved.text
    config = await _config(db, project_id)
    assert config["confluence_url"] == "https://your-site.atlassian.net" and config["confluence_allowed_spaces"]

    refused = await client.put(url, json={"is_active": True, "limits": {"confluence_allowed_spaces": [{"x": 1}]}})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "connector_access_invalid"
    assert (await _config(db, project_id))["confluence_allowed_spaces"] == [{"space_key": "ENG", "enabled": True}]


async def _failing_stub():
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 401 Unauthorized\r\nContent-Type: application/json\r\nConnection: close\r\n"
                     b"Content-Length: 2\r\n\r\n{}")
        await writer.drain()
        writer.close()

    return await asyncio.start_server(handle, "127.0.0.1", 0)


async def test_r3_a_workspace_test_records_health_but_never_feeds_the_global_breaker(client, db, monkeypatch):
    await _login(client)
    project_id = await _project(db)
    url = f"{PANEL}/projects/{project_id}/connectors/confluence/connection"
    server = await _failing_stub()
    base = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    try:
        use_stub_settings(monkeypatch, stub_settings(hosts=base.removeprefix("http://")))
        assert (await client.put(url, json=_own(base, confluence_password=PASSWORD))).status_code == 200
        for _ in range(4):
            assert (await client.post(f"{url}/test", json={})).json()["ok"] is False
    finally:
        server.close()
        await server.wait_closed()
    assert (await list_connector_health_rows(db))[("confluence", project_id)].status == "error"
    assert not [row for row in await list_circuit_breakers(db) if row["connector_name"] == "confluence"]


async def test_r4_a_mode_switch_leaves_one_credential_unit(client, db):
    await _login(client)
    project_id = await _project(db)
    url = f"{PANEL}/projects/{project_id}/connectors/confluence/connection"
    target = "https://wiki.example.test/wiki"
    assert (await client.put(url, json=_own(target, confluence_password=PASSWORD))).status_code == 200
    switched = await client.put(url, json={"source": "workspace", "confluence_url": target,
                                           "confluence_auth_mode": "bearer_pat", "confluence_token": "pat"})
    assert switched.status_code == 200, switched.text
    config = await _config(db, project_id)
    assert "confluence_username" not in config and "confluence_password_secret_ref" not in config
    assert config["confluence_token_secret_ref"] and config["confluence_auth_mode"] == "bearer_pat"

    jira = f"{PANEL}/projects/{project_id}/connectors/jira/connection"
    assert (await client.put(jira, json={"source": "workspace", "jira_url": "https://jira.example.test",
                                         "jira_auth_mode": "cloud_api_token", "jira_email": "me@example.test",
                                         "jira_token": "t"})).status_code == 200
    assert (await client.put(jira, json={"source": "workspace", "jira_url": "https://jira.example.test",
                                         "jira_auth_mode": "basic", "jira_username": "svc",
                                         "jira_password": "p"})).status_code == 200
    config = await _config(db, project_id, "jira")
    assert "jira_email" not in config and "jira_token_secret_ref" not in config
    assert config["jira_username"] == "svc" and config["jira_password_secret_ref"]


async def test_r5_a_disabled_global_entry_is_configured_but_not_active(client, db):
    await _login(client)
    project_id = await _project(db)
    url = f"{PANEL}/projects/{project_id}/connectors/confluence/connection"
    assert (await client.get(url)).json()["global"]["configured"] is False
    entry = BuiltInToolConfig(tool_name="confluence", project_id=None, is_active=False,
                              config={"confluence_url": "https://wiki.example.test/wiki"})
    db.add(entry)
    await db.commit()
    described = (await client.get(url)).json()["global"]
    assert (described["configured"], described["active"]) == (True, False)
    entry.is_active = True
    await db.commit()
    assert (await client.get(url)).json()["global"]["active"] is True


def test_the_two_stub_credential_is_basic() -> None:
    assert BASIC == "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
