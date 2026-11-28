"""Shared helpers for the test_mcp_server_registry_* modules."""

from __future__ import annotations

import uuid

from app.models import Project
from app.services.secret import set_secret_value

CATALOG = {
    "context7": {
        "slug": "context7",
        "name": "Context7",
        "transport": "streamable-http",
        "url": "https://mcp.context7.com/mcp",
        "default_name": "context7",
        "fields": [
            {
                "name": "context7_api_key",
                "type": "password",
                "required": True,
                "header": "CONTEXT7_API_KEY",
                "header_aliases": ["Context7-API-Key"],
            }
        ],
    }
}


class FakeMcpClientManager:
    def __init__(self, *, connection_result: bool = True):
        self.connection_result = connection_result
        self.registered = []
        self.connect_calls = []
        self.disconnected = []

    async def is_connected(self, name):
        return name in self.connect_calls and self.connection_result

    def get_tools(self, name):
        return []

    def register_server(self, config):
        self.registered.append(config)

    def get_server(self, name):
        return next((config for config in reversed(self.registered) if config.name == name), None)

    async def connect(self, name):
        self.connect_calls.append(name)
        return self.connection_result

    async def disconnect(self, name):
        self.disconnected.append(name)
        return True

    def unregister_server(self, name):
        self.registered = [config for config in self.registered if config.name != name]


async def _workspace(db, *, enabled: bool = True) -> Project:
    name = f"mcp-{uuid.uuid4().hex[:8]}"
    config = {"mcp_policy": {"enabled_servers": ["context7"]}} if enabled else {}
    project = Project(name=name, config=config, is_active=True)
    db.add(project)
    await db.flush()
    return project


async def _context7_secret(
    db,
    project: Project,
    *,
    field_name: str = "context7_api_key",
    value: str = "must-never-leave-runtime-config",
):
    return await set_secret_value(
        db,
        tool_name="mcp:context7",
        field_name=field_name,
        project_id=project.id,
        value=value,
    )
