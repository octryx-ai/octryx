"""The MCP catalog persists secret references and resolves them only for connect."""

import pytest
from sqlalchemy import select

import app.plugins.mcp.client as mcp_client_module
from app.models import Project
from app.services.secret import set_secret_value


class FakeManager:
    def __init__(self):
        self._servers = {}
        self._connected = set()

    def list_servers(self):
        return list(self._servers.values())

    def get_server(self, name):
        return self._servers.get(name)

    def register_server(self, config):
        self._servers[config.name] = config

    def unregister_server(self, name):
        self._servers.pop(name, None)

    async def is_connected(self, name):
        return name in self._connected

    async def connect(self, name):
        if name in self._servers:
            self._connected.add(name)
            return True
        return False

    async def disconnect(self, name):
        self._connected.discard(name)
        return True

    def get_tools(self, name=None):
        if name in self._connected:
            return [type("Tool", (), {"name": "demo", "description": "demo"})()]
        return []


async def _enable_catalog_servers(db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    project.config = {
        **dict(project.config or {}),
        "mcp_policy": {"enabled_servers": ["aws-knowledge", "context7"]},
    }
    await db.commit()
    return project


async def _assert_remote_catalog(client, project):
    catalog_resp = await client.get(
        "/admin/chat/api/panel/mcp/catalog",
        params={"workspace_id": project.id},
    )
    assert catalog_resp.status_code == 200
    catalog = catalog_resp.json()
    catalog_by_slug = {item["slug"]: item for item in catalog}
    slugs = {item["slug"] for item in catalog}
    assert slugs == {"context7", "aws-knowledge"}
    # Only remote servers: the API pod has no npx, uvx or docker for stdio presets.
    assert {item["transport"] for item in catalog} == {"streamable-http"}
    assert catalog_by_slug["context7"]["transport"] == "streamable-http"
    assert catalog_by_slug["context7"]["source_url"] == "https://github.com/upstash/context7#installation"


async def _install_aws_knowledge_without_registering(client, project, fake_manager):
    install_resp = await client.post(
        "/admin/chat/api/panel/mcp/catalog/aws-knowledge/install",
        json={
            "owner_scope": "workspace",
            "workspace_id": project.id,
            "name": "aws-knowledge",
            "auto_start": True,
            "is_active": False,
            "settings": {},
        },
    )
    assert install_resp.status_code == 200
    installed = install_resp.json()
    assert installed["name"] == "aws-knowledge"
    assert installed["catalog_slug"] == "aws-knowledge"
    assert installed["connected"] is False
    assert installed["settings"] == {}
    assert fake_manager._servers == {}

    listed_resp = await client.get(
        "/admin/chat/api/panel/mcp/servers",
        params={"workspace_id": project.id},
    )
    assert listed_resp.status_code == 200
    servers = listed_resp.json()
    assert servers[0]["catalog_slug"] == "aws-knowledge"


async def _install_context7_with_secret_ref(client, db, project):
    raw_secret_resp = await client.post(
        "/admin/chat/api/panel/mcp/catalog/context7/install",
        json={
            "owner_scope": "workspace",
            "workspace_id": project.id,
            "values": {"context7_api_key": ("ctx7" + "-raw-key-must-be-rejected")},
        },
    )
    assert raw_secret_resp.status_code == 422

    secret = await set_secret_value(
        db,
        tool_name="mcp:context7",
        field_name="context7_api_key",
        project_id=project.id,
        value="ctx7-test-key",
    )
    await db.commit()

    context7_resp = await client.post(
        "/admin/chat/api/panel/mcp/catalog/context7/install",
        json={
            "owner_scope": "workspace",
            "workspace_id": project.id,
            "auto_start": False,
            "is_active": True,
            "secret_refs": {"context7_api_key": f"secret:{secret.id}"},
        },
    )
    assert context7_resp.status_code == 200
    context7 = context7_resp.json()
    assert context7["name"] == "context7"
    assert context7["catalog_slug"] == "context7"
    assert context7["transport"] == "streamable-http"
    assert context7["url"] == "https://mcp.context7.com/mcp"
    assert context7["secret_fields"] == ["context7_api_key"]
    assert context7["credential_binding_count"] == 1
    assert "headers" not in context7
    assert "env" not in context7
    assert secret.id not in str(context7)
    assert "ctx7-test-key" not in str(context7)
    return secret


async def _assert_connect_resolves_secret(client, project, fake_manager, secret):
    connect_resp = await client.post(
        "/admin/chat/api/panel/mcp/servers/context7/connect",
        params={"workspace_id": project.id},
    )
    assert connect_resp.status_code == 200
    assert connect_resp.json()["connected"] is True
    context7_runtime = fake_manager._servers["context7"]
    assert context7_runtime.command == ""
    assert context7_runtime.args == []
    assert context7_runtime.headers == {
        "CONTEXT7_API_KEY": "ctx7-test-key",
        "Context7-API-Key": "ctx7-test-key",
    }
    assert context7_runtime.metadata["catalog_slug"] == "context7"
    assert "ctx7-test-key" not in str(connect_resp.json())
    assert secret.id not in str(connect_resp.json())


@pytest.mark.asyncio
async def test_mcp_catalog_persists_secret_references_and_resolves_them_only_for_connect(admin_client, db, monkeypatch):
    fake_manager = FakeManager()
    monkeypatch.setattr(mcp_client_module, "mcp_client_manager", fake_manager)
    project = await _enable_catalog_servers(db)

    await _assert_remote_catalog(admin_client, project)
    await _install_aws_knowledge_without_registering(admin_client, project, fake_manager)
    secret = await _install_context7_with_secret_ref(admin_client, db, project)
    await _assert_connect_resolves_secret(admin_client, project, fake_manager, secret)

    fresh_manager = FakeManager()
    monkeypatch.setattr(mcp_client_module, "mcp_client_manager", fresh_manager)
    persisted_resp = await admin_client.get(
        "/admin/chat/api/panel/mcp/servers",
        params={"workspace_id": project.id},
    )
    assert persisted_resp.status_code == 200
    persisted_servers = {server["name"]: server for server in persisted_resp.json()}
    assert persisted_servers["context7"]["catalog_slug"] == "context7"
    assert persisted_servers["context7"]["secret_fields"] == ["context7_api_key"]
    assert secret.id not in str(persisted_servers["context7"])
    assert "ctx7-test-key" not in str(persisted_servers["context7"])
    assert fresh_manager._servers == {}
