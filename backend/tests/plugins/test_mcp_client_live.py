"""A real MCP server over stdio and streamable HTTP. Fakes let ``initialize()`` answer on an unentered
session; the SDK starts its receive loop in ``__aenter__``, so only a real server proves the client."""

from __future__ import annotations

import asyncio
import socket
import sys
import textwrap
from pathlib import Path

import pytest

import app.plugins.mcp.client as mcp_client
from app.plugins.mcp.client import MCPClientManager, resolve_stdio_command
from app.plugins.mcp.models import MCPServerConfig, TransportType

ECHO_SERVER = textwrap.dedent(
    '''
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("echo")


    @app.tool()
    def echo(text: str) -> str:
        """Echo the text back."""
        return text


    if __name__ == "__main__":
        app.run()
    '''
)


def _echo_app():
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("echo")

    @app.tool()
    def echo(text: str) -> str:
        return text

    return app


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _call_echo(manager: MCPClientManager, config: MCPServerConfig) -> dict:
    manager.register_server(config)
    assert await manager.connect(config.name) is True
    assert [tool.name for tool in manager.get_tools(config.name)] == ["echo"]
    result = await manager.call_tool(config.name, "echo", {"text": "hi"})
    assert await manager.disconnect(config.name) is True
    return result


@pytest.mark.asyncio
async def test_stdio_server_connects_answers_and_stops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = tmp_path / "echo_server.py"
    script.write_text(ECHO_SERVER)
    interpreter_dir = str(Path(sys.executable).parent) + "/"
    monkeypatch.setattr(mcp_client, "STDIO_ALLOWED_PREFIXES", (interpreter_dir,))
    # The echo server is a fresh interpreter that imports FastMCP (pydantic, starlette) before it answers. Under a
    # full parallel suite that start can outlast the product's 30 s connect allowance, while alone it takes about a
    # second. This test is about connecting and answering, so it gives the start more room.
    monkeypatch.setattr(mcp_client, "MCP_HTTP_CONNECT_TIMEOUT_SECONDS", 300.0)

    result = await _call_echo(
        MCPClientManager(),
        MCPServerConfig(name="echo", transport=TransportType.STDIO, command=sys.executable, args=[str(script)]),
    )
    assert result == {"success": True, "content": [{"type": "text", "text": "hi"}]}


@pytest.mark.asyncio
async def test_streamable_http_server_connects_answers_and_stops() -> None:
    import uvicorn

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(_echo_app().streamable_http_app(), host="127.0.0.1", port=port,
                                           log_level="warning"))
    serving = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)
        result = await _call_echo(
            MCPClientManager(),
            MCPServerConfig(name="echo", command="", transport=TransportType.STREAMABLE_HTTP,
                            url=f"http://127.0.0.1:{port}/mcp"),
        )
    finally:
        server.should_exit = True
        await serving
    assert result == {"success": True, "content": [{"type": "text", "text": "hi"}]}


def test_a_bare_command_is_looked_up_on_path_and_must_live_in_an_allowed_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_client.shutil, "which", lambda name: "/usr/local/bin/npx" if name == "npx" else None)
    monkeypatch.setattr(mcp_client.os, "access", lambda path, mode: True)
    assert resolve_stdio_command("npx") == "/usr/local/bin/npx"
    assert resolve_stdio_command("uvx") is None  # not installed
    assert resolve_stdio_command("/opt/tools/server") is None  # outside the allowed directories
    assert resolve_stdio_command("") is None
