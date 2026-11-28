"""The recording fake MCP client of the governed MCP resource/prompt suites (``mcp_resource_support``)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.plugins.mcp.models import MCPPrompt, MCPResource
from tests.support.mcp_resource_support import SERVER

__all__ = [
    "RecordingMcpResourceManager",
    "install_mcp_manager",
]


class _FakeMcpSession:
    def __init__(self, manager: RecordingMcpResourceManager, name: str) -> None:
        self._manager = manager
        self._name = name

    async def list_resources(self) -> SimpleNamespace:
        self._manager.resource_lists.append(self._name)
        if self._manager.resource_discovery_error is not None:
            raise self._manager.resource_discovery_error
        return SimpleNamespace(
            resources=[
                SimpleNamespace(
                    uri=resource.uri,
                    name=resource.name,
                    description=resource.description,
                    mimeType=resource.mime_type,
                )
                for resource in self._manager._resources
            ]
        )

    async def list_prompts(self) -> SimpleNamespace:
        self._manager.prompt_lists.append(self._name)
        if self._manager.prompt_discovery_error is not None:
            raise self._manager.prompt_discovery_error
        return SimpleNamespace(
            prompts=[
                SimpleNamespace(
                    name=prompt.name,
                    description=prompt.description,
                    arguments=[
                        SimpleNamespace(
                            name=argument.get("name"),
                            description=argument.get("description"),
                            required=argument.get("required", False),
                        )
                        for argument in (prompt.arguments or [])
                    ],
                )
                for prompt in self._manager._prompts
            ]
        )


class RecordingMcpResourceManager:
    def __init__(
        self,
        resources: list[MCPResource] | None = None,
        prompts: list[MCPPrompt] | None = None,
        *,
        configured_servers: list[str] | None = None,
        resource_discovery_error: BaseException | None = None,
        prompt_discovery_error: BaseException | None = None,
        session_available: bool = True,
        connection_persists: bool = True,
    ) -> None:
        self._resources = list(resources or [])
        self._prompts = list(prompts or [])
        self._configured_servers = [SERVER] if configured_servers is None else list(configured_servers)
        self.resource_discovery_error = resource_discovery_error
        self.prompt_discovery_error = prompt_discovery_error
        self.session_available = session_available
        self.connection_persists = connection_persists
        self._connected: set[str] = set()
        self._server_configs: dict[str, Any] = {}
        self.connects: list[str] = []
        self.resource_reads: list[tuple[str, str]] = []
        self.prompt_gets: list[tuple[str, str, dict]] = []
        self.resource_lists: list[str] = []
        self.prompt_lists: list[str] = []

    def get_server(self, name: str) -> object | None:
        if name in self._server_configs:
            return self._server_configs[name]
        return object() if name in self._configured_servers else None

    def register_server(self, config: Any) -> None:
        self._server_configs[config.name] = config
        if config.name not in self._configured_servers:
            self._configured_servers.append(config.name)

    def unregister_server(self, name: str) -> None:
        self._server_configs.pop(name, None)
        self._connected.discard(name)

    def get_tools(self, name: str) -> list[Any]:
        return []

    def list_servers(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(name=name) for name in self._configured_servers]

    def get_session(self, name: str) -> object | None:
        if not self.session_available or name not in self._configured_servers:
            return None
        return _FakeMcpSession(self, name)

    async def is_connected(self, name: str) -> bool:
        return name in self._connected

    async def connect(self, name: str) -> bool:
        self.connects.append(name)
        if self.connection_persists:
            self._connected.add(name)
        return True

    async def list_resources(self, name: str) -> list[MCPResource]:
        self.resource_lists.append(name)
        return list(self._resources)

    async def read_resource(self, name: str, uri: str) -> dict[str, Any]:
        self.resource_reads.append((name, uri))
        return {"success": True, "contents": [{"type": "text", "text": "# React"}]}

    async def list_prompts(self, name: str) -> list[MCPPrompt]:
        self.prompt_lists.append(name)
        return list(self._prompts)

    async def get_prompt(self, name: str, prompt_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.prompt_gets.append((name, prompt_name, dict(arguments)))
        return {"success": True, "messages": [{"role": "user", "content": "Summarize react"}]}

    @property
    def touched_remote(self) -> bool:
        return bool(
            self.connects or self.resource_reads or self.prompt_gets or self.resource_lists or self.prompt_lists
        )


def install_mcp_manager(monkeypatch, manager: RecordingMcpResourceManager) -> RecordingMcpResourceManager:
    monkeypatch.setattr("app.plugins.mcp.client.mcp_client_manager", manager)
    return manager
