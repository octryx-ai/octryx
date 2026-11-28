"""Contract: a Workspace's own Confluence/Jira connection survives access saves and failed tests, through
the real admin panel routes and a loopback Confluence stub."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import uuid

import pytest
from sqlalchemy import select

from app.models import BuiltInToolConfig
from app.services.connector_health import list_connector_health_rows
from app.services.secret import get_secret_value
from tests.conftest import ADMIN_PASSWORD
from tests.egress_support import stub_settings, use_stub_settings
from tests.factories import make_project

USER, PASSWORD = "svc", "pw-saved"
BASIC = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
PANEL = "/admin/chat/api/panel"


@contextlib.asynccontextmanager
async def _stub():
    seen: list[str] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = (await reader.readuntil(b"\r\n\r\n")).decode("latin-1")
        auth = next((line.split(":", 1)[1].strip() for line in head.split("\r\n")
                     if line.lower().startswith("authorization:")), "")
        seen.append(auth)
        ok = auth == BASIC
        body = b'{"size": 1}' if ok else b'{"message": "denied"}'
        writer.write((b"HTTP/1.1 200 OK" if ok else b"HTTP/1.1 401 Unauthorized")
                     + b"\r\nContent-Type: application/json\r\nConnection: close\r\n"
                     + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}", seen
    finally:
        server.close()
        await server.wait_closed()


async def _login(client) -> None:
    response = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert response.status_code == 303


async def _project(db) -> str:
    return (await make_project(db, name=f"conn-{uuid.uuid4().hex[:8]}", commit=True)).id


def _own(url: str, **extra) -> dict:
    return {"source": "workspace", "confluence_url": url, "confluence_auth_mode": "basic",
            "confluence_username": USER, **extra}


async def _project_config(db, project_id: str) -> dict:
    entry = (await db.execute(select(BuiltInToolConfig).where(
        BuiltInToolConfig.tool_name == "confluence", BuiltInToolConfig.project_id == project_id))).scalar_one()
    await db.refresh(entry)
    return dict(entry.config or {})


async def test_access_save_never_wipes_the_workspace_connection_and_global_switch_clears_it(admin_client, db):
    project_id = await _project(db)
    url = f"{PANEL}/projects/{project_id}/connectors/confluence"
    saved = await admin_client.put(f"{url}/connection", json=_own("https://wiki.example.test/wiki",
                                                            confluence_password=PASSWORD))
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["source"] == "workspace" and body["secret_status"]["confluence_password"] is True
    assert PASSWORD not in saved.text and "secret_ref" not in saved.text

    access = await admin_client.put(url, json={"is_active": True,
                                         "limits": {"confluence_allowed_spaces": [{"space_key": "ENG", "enabled": True}]}})
    assert access.status_code == 200, access.text
    config = await _project_config(db, project_id)
    assert config["confluence_url"] == "https://wiki.example.test/wiki" and config["confluence_auth_mode"] == "basic"
    assert config["confluence_password_secret_ref"] and config["confluence_allowed_spaces"]
    again = (await admin_client.get(f"{url}/connection")).json()
    assert again["source"] == "workspace" and again["fields"]["confluence_username"] == USER

    back = await admin_client.put(f"{url}/connection", json={"source": "global"})
    assert back.status_code == 200 and back.json()["source"] == "global" and back.json()["fields"] == {}
    config = await _project_config(db, project_id)
    assert not any(key.startswith(("confluence_url", "confluence_auth", "confluence_user", "confluence_pass"))
                   for key in config)
    assert config["confluence_allowed_spaces"], "allowlists stay"
    entry = (await db.execute(select(BuiltInToolConfig).where(BuiltInToolConfig.project_id == project_id))).scalar_one()
    assert entry.is_active is True, "access stays as saved"


async def test_a_typed_secret_is_used_for_the_test_only_and_the_saved_one_stays(admin_client, db, monkeypatch):
    project_id = await _project(db)
    url = f"{PANEL}/projects/{project_id}/connectors/confluence/connection"
    async with _stub() as (base, seen):
        use_stub_settings(monkeypatch, stub_settings(hosts=base.removeprefix("http://")))
        assert (await admin_client.put(url, json=_own(base, confluence_password=PASSWORD))).status_code == 200

        wrong = (await admin_client.post(f"{url}/test", json=_own(base, confluence_password="typed-wrong"))).json()
        assert wrong["ok"] is False and wrong["http_status"] == 401 and "typed-wrong" not in str(wrong)
        empty = (await admin_client.post(f"{url}/test", json=_own(base, confluence_password=""))).json()
        assert empty["ok"] is True, empty
        assert seen[-1] == BASIC
        assert await get_secret_value(db, tool_name="confluence", field_name="confluence_password",
                                      project_id=project_id, purpose="test.read") == PASSWORD

        # The /admin/tools test route never stores a typed secret either.
        legacy = await admin_client.post("/admin/tools/configs/test", data={
            "tool_name": "confluence", "project_id": project_id,
            "config_json": f'{{"confluence_url": "{base}", "confluence_auth_mode": "basic", "confluence_username": "{USER}"}}',
            "confluence_password": "legacy-wrong",
        })
        assert legacy.status_code == 200
        assert await get_secret_value(db, tool_name="confluence", field_name="confluence_password",
                                      project_id=project_id, purpose="test.read") == PASSWORD
        assert (await admin_client.post(f"{url}/test", json={})).json()["ok"] is True


async def test_saved_connection_tests_are_recorded_as_health_and_typed_ones_are_not(admin_client, db, monkeypatch):
    project_id = await _project(db)
    url = f"{PANEL}/projects/{project_id}/connectors/confluence/connection"
    async with _stub() as (base, _seen):
        use_stub_settings(monkeypatch, stub_settings(hosts=base.removeprefix("http://")))
        assert (await admin_client.put(url, json=_own(base, confluence_password=PASSWORD))).status_code == 200
        await admin_client.post(f"{url}/test", json=_own(base, confluence_password="typed-wrong"))
        assert (await list_connector_health_rows(db)).get(("confluence", project_id)) is None
        assert (await admin_client.post(f"{url}/test", json={})).json()["ok"] is True
        assert (await admin_client.get(url)).json()["health"]["status"] == "ok"

        # The global card: a successful manual test updates its health too.
        saved = await admin_client.put(f"{PANEL}/connectors/confluence", json={
            "confluence_url": base, "confluence_auth_mode": "basic", "confluence_username": USER,
            "confluence_password": PASSWORD})
        assert saved.status_code == 200, saved.text
        assert (await admin_client.post(f"{PANEL}/connectors/confluence/test")).json()["ok"] is True
        rows = await list_connector_health_rows(db)
        assert rows[("confluence", "")].status == "ok"


@pytest.mark.parametrize(("body", "code"), [
    (_own("https://your-site.atlassian.net", confluence_password="x"), "confluence_cloud_url_without_wiki"),
    ({**_own("https://wiki.example.test/wiki"), "confluence_auth_mode": "oauth", "confluence_password": "x"},
     "atlassian_auth_invalid"),
    ({**_own("https://wiki.example.test/wiki"), "confluence_auth_mode": "bearer_pat", "confluence_password": "x"},
     "atlassian_auth_invalid"),
    ({"source": "workspace", "confluence_auth_mode": "basic", "confluence_username": "u", "confluence_password": "x"},
     "atlassian_auth_invalid"),
    ({"source": "elsewhere"}, "connection_source_invalid"),
])
async def test_invalid_workspace_saves_are_422_with_a_code_and_store_nothing(admin_client, db, body, code):
    project_id = await _project(db)
    refused = await admin_client.put(f"{PANEL}/projects/{project_id}/connectors/confluence/connection", json=body)
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == code
    assert "x" not in refused.json()["detail"]["message"].split()
    stored = (await db.execute(select(BuiltInToolConfig).where(BuiltInToolConfig.project_id == project_id))).scalars().all()
    assert stored == []


async def test_the_global_save_refuses_a_bare_cloud_url_and_unknown_connectors_are_404(admin_client, db):
    refused = await admin_client.put(f"{PANEL}/connectors/confluence", json={
        "confluence_url": "https://your-site.atlassian.net", "confluence_auth_mode": "cloud_api_token",
        "confluence_username": "me@example.test", "confluence_token": "t"})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "confluence_cloud_url_without_wiki"
    project_id = await _project(db)
    assert (await admin_client.get(f"{PANEL}/projects/{project_id}/connectors/github/connection")).status_code == 404


async def test_a_kept_secret_never_silently_follows_a_changed_url(admin_client, db):
    project_id = await _project(db)
    url = f"{PANEL}/projects/{project_id}/connectors/confluence/connection"
    assert (await admin_client.put(url, json=_own("https://wiki.example.test/wiki", confluence_password=PASSWORD))).status_code == 200
    moved = await admin_client.put(url, json=_own("https://other.example.test/wiki"))
    assert moved.status_code == 409 and moved.json()["detail"]["state"] == "secret_rebind_required"
    assert (await _project_config(db, project_id))["confluence_url"] == "https://wiki.example.test/wiki"
    confirmed = await admin_client.put(url, json=_own("https://other.example.test/wiki", confirm_secret_rebind=True))
    assert confirmed.status_code == 200 and confirmed.json()["fields"]["confluence_url"] == "https://other.example.test/wiki"


async def test_limits_count_only_non_empty_values(admin_client, db):
    project_id = await _project(db)
    db.add(BuiltInToolConfig(tool_name="confluence", project_id=None, is_active=True, config={
        "confluence_url": "https://wiki.example.test/wiki",
        "confluence_allowed_spaces": [{"space_key": "ENG", "enabled": True}],
        "confluence_allowed_pages": [],
    }))
    db.add(BuiltInToolConfig(tool_name="confluence", project_id=project_id, is_active=True, config={}))
    await db.commit()
    listing = (await admin_client.get(f"{PANEL}/projects/{project_id}/connectors")).json()
    confluence = next(item for item in listing["connectors"] if item["connector_name"] == "confluence")
    assert list(confluence["inherited_limits"]) == ["confluence_allowed_spaces"]
    assert list(confluence["effective_limits"]) == ["confluence_allowed_spaces"]
