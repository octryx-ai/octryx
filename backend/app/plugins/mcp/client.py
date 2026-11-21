"""MCP client manager for connecting to MCP servers."""

import asyncio
import contextlib
import logging
import os
import shlex
import shutil
import time
from typing import Any

from app.services.error_facts import error_text

from ...tools.results import safe_tool_error_message
from ._payloads import normalize_content_items, normalize_prompt_messages
from .catalog_discovery import discover_mcp_prompts, discover_mcp_resources
from .models import MCPPrompt, MCPResource, MCPServerConfig, MCPTool, OAuthConfig, TransportType
from .oauth import _auth_headers, _ensure_token, _oauth_fetch_token, _oauth_register_client
from .session_runner import McpSessionRunner

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.sse import sse_client
    from mcp.client.stdio import stdio_client

    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    ClientSession = None
    StdioServerParameters = None

log = logging.getLogger(__name__)

MCP_HTTP_CONNECT_TIMEOUT_SECONDS = 30.0
MCP_HTTP_DISCOVERY_TIMEOUT_SECONDS = 30.0
STDIO_ALLOWED_PREFIXES = ("/usr/local/bin/", "/usr/bin/", "/usr/local/mcp-servers/")


def resolve_stdio_command(command: str | None) -> str | None:
    """The executable a stdio server runs, or ``None`` when it is not installed in an allowed directory.

    A bare name (``npx``) is looked up on ``PATH``; ``Path(...).resolve()`` turned it into ``<cwd>/npx`` and refused
    every catalog preset. The located path is checked as found, without following
    symlinks: package managers install their launchers in ``/usr/local/bin`` as links into their own trees.
    """
    raw = str(command or "").strip()
    if not raw:
        return None
    located = raw if os.path.isabs(raw) else shutil.which(raw)
    if not located:
        return None
    located = os.path.abspath(located)
    if not located.startswith(STDIO_ALLOWED_PREFIXES) or not os.access(located, os.X_OK):
        return None
    return located


class MCPClientManager:
    """Manages connections to MCP servers."""

    def __init__(self):
        self._servers: dict[str, MCPServerConfig] = {}
        self._sessions: dict[str, ClientSession] = {}
        self._tools: dict[str, list[MCPTool]] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._http_clients: dict[str, Any] = {}
        self._http_contexts: dict[str, Any] = {}
        self._runners: dict[str, McpSessionRunner] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._oauth_configs: dict[str, OAuthConfig] = {}
        self._tool_list_change_callbacks: list = []

    def register_server(self, config: MCPServerConfig) -> None:
        """Register an MCP server configuration."""
        self._servers[config.name] = config
        self._locks[config.name] = asyncio.Lock()

    def _schedule_session_close(self, session: ClientSession) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            loop.create_task(session.close())
            return
        try:
            asyncio.run(session.close())
        except Exception:
            log.exception("Failed to close MCP session during unregister")

    def _schedule_runner_stop(self, runner: McpSessionRunner) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            loop.create_task(runner.stop())

    def unregister_server(self, name: str) -> None:
        """Unregister an MCP server."""
        session = self._sessions.pop(name, None)
        runner = self._runners.pop(name, None)
        if runner is not None:
            self._schedule_runner_stop(runner)
        elif session is not None:
            self._schedule_session_close(session)
        self._tools.pop(name, None)
        process = self._processes.pop(name, None)
        if process is not None:
            try:
                process.terminate()
            except (OSError, ProcessLookupError):
                log.exception("Failed to terminate MCP process during unregister: %s", name)
        http_context = self._http_contexts.pop(name, None)
        if http_context is not None:
            self._schedule_async_exit(http_context)
        http_client = self._http_clients.pop(name, None)
        if http_client is not None:
            self._schedule_async_close(http_client)
        self._oauth_configs.pop(name, None)
        if name in self._servers:
            del self._servers[name]
        if name in self._locks:
            del self._locks[name]

    def get_server(self, name: str) -> MCPServerConfig | None:
        """Get a server configuration by name."""
        return self._servers.get(name)

    def get_session(self, name: str) -> Any | None:
        """Get the live session for a server, or ``None`` when not connected."""
        return self._sessions.get(name)

    def _schedule_async_close(self, closeable: Any) -> None:
        close = getattr(closeable, "aclose", None) or getattr(closeable, "close", None)
        if close is None:
            return
        try:
            result = close()
        except Exception:
            log.exception("Failed to close MCP HTTP client")
            return
        if not asyncio.iscoroutine(result):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            loop.create_task(result)
            return
        try:
            asyncio.run(result)
        except Exception:
            log.exception("Failed to close MCP HTTP client")

    def _schedule_async_exit(self, context: Any) -> None:
        exit_context = getattr(context, "__aexit__", None)
        if exit_context is None:
            return
        try:
            result = exit_context(None, None, None)
        except Exception:
            log.exception("Failed to close MCP HTTP stream")
            return
        if not asyncio.iscoroutine(result):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            loop.create_task(result)
            return
        try:
            asyncio.run(result)
        except Exception:
            log.exception("Failed to close MCP HTTP stream")

    def list_servers(self) -> list[MCPServerConfig]:
        """List all registered servers."""
        return list(self._servers.values())

    async def connect(self, name: str) -> bool:
        """Connect to an MCP server and discover its capabilities."""
        if not MCP_AVAILABLE:
            log.error("MCP package not installed. Install with: pip install mcp")
            return False

        config = self._servers.get(name)
        if not config:
            log.error(f"MCP server '{name}' not registered")
            return False

        try:
            if config.transport == TransportType.STDIO:
                return await self._connect_stdio(name, config)
            elif config.transport in (TransportType.SSE, TransportType.STREAMABLE_HTTP):
                return await self._connect_http(name, config)
            else:
                log.error(f"Unsupported transport type: {config.transport}")
                return False
        except Exception as e:
            log.error("Failed to connect to MCP server '%s': %s", name, error_text("mcp_connect_failed", e))
            return False

    async def _connect_stdio(self, name: str, config: MCPServerConfig) -> bool:
        """Connect to an MCP server using stdio transport."""
        command = resolve_stdio_command(config.command)
        if command is None:
            log.error("MCP stdio: command '%s' is not installed in an allowed path %s", config.command,
                      STDIO_ALLOWED_PREFIXES)
            return False
        # Validate that args contain no shell metacharacters
        if config.args:
            for arg in config.args:
                try:
                    shlex.split(arg)
                except ValueError:
                    log.error(f"MCP stdio: arg '{arg}' contains shell metacharacters")
                    return False
        server_params = StdioServerParameters(
            command=command,
            args=config.args,
            env=config.env if config.env else None,
        )
        try:
            return await self._start_runner(name, lambda: stdio_client(server_params), "stdio")
        except Exception as e:
            log.error("Failed to connect via stdio to '%s': %s", name, error_text("mcp_stdio_connect_failed", e))
            return False

    async def _start_runner(self, name: str, open_streams: Any, label: str) -> bool:
        """Hold the transport and the session open in their own task (``session_runner``), then discover."""
        runner = McpSessionRunner(name, open_streams, ClientSession)
        session = await runner.start(MCP_HTTP_CONNECT_TIMEOUT_SECONDS)
        self._runners[name] = runner
        self._sessions[name] = session
        await self._discover_capabilities(name, session)
        log.info("Connected to MCP server '%s' via %s", name, label)
        return True

    async def _connect_http(self, name: str, config: MCPServerConfig) -> bool:
        """Connect to an MCP server using SSE or StreamableHTTP transport, with optional OAuth."""
        if not config.url:
            log.error(f"URL required for HTTP transport on server '{name}'")
            return False

        # Handle OAuth: register client + fetch token
        if config.oauth:
            await _oauth_register_client(config.oauth, config.url)
            token = await _ensure_token(config.oauth)
            if not token:
                log.warning(f"OAuth token unavailable for '{name}'; attempting unauthenticated connection")
            self._oauth_configs[name] = config.oauth

        # Build extra headers for authenticated connections. Static headers are
        # intended for remote MCP servers that require a provider-specific API
        # key header instead of OAuth.
        headers = dict(config.headers or {})
        if config.oauth:
            headers.update(_auth_headers(config.oauth))

        try:
            if config.transport == TransportType.STREAMABLE_HTTP:
                # Try mcp.client.streamable_http if available, fall back to SSE
                try:
                    from mcp.client.streamable_http import streamable_http_client

                    http_client = None
                    client_kwargs: dict[str, Any] = {}
                    if headers:
                        import httpx

                        http_client = httpx.AsyncClient(headers=headers)
                        client_kwargs["http_client"] = http_client
                        self._http_clients[name] = http_client
                    return await self._start_runner(
                        name, lambda: streamable_http_client(config.url, **client_kwargs), "StreamableHTTP"
                    )
                except (ImportError, TypeError):
                    # Fallback: use SSE transport
                    log.debug("streamable_http_client not available, falling back to SSE for '%s'", name)
                    http_client = self._http_clients.pop(name, None)
                    if http_client is not None:
                        with contextlib.suppress(Exception):
                            await http_client.aclose()

            # SSE transport (also fallback for streamable-http)
            try:
                return await self._start_runner(name, lambda: sse_client(config.url, headers=headers), "SSE")
            except TypeError:
                # An mcp lib whose sse_client takes no headers
                return await self._start_runner(name, lambda: sse_client(config.url), "SSE (no auth headers)")

        except Exception as e:
            log.error("Failed to connect via HTTP to '%s': %s", name, error_text("mcp_http_connect_failed", e))
            self._sessions.pop(name, None)
            runner = self._runners.pop(name, None)
            if runner is not None:
                await runner.stop()
            http_context = self._http_contexts.pop(name, None)
            if http_context is not None:
                with contextlib.suppress(Exception):
                    await http_context.__aexit__(None, None, None)
            http_client = self._http_clients.pop(name, None)
            if http_client is not None:
                with contextlib.suppress(Exception):
                    await http_client.aclose()
            return False

    async def refresh_token(self, name: str) -> bool:
        """Manually refresh the OAuth token for a server."""
        oauth = self._oauth_configs.get(name)
        if not oauth:
            return False
        return await _oauth_fetch_token(oauth)

    def get_auth_status(self, name: str) -> dict:
        """Return OAuth status for a server."""
        oauth = self._oauth_configs.get(name)
        if not oauth:
            return {"needs_auth": False}
        needs_registration = not oauth.client_id and bool(oauth.registration_url)
        needs_auth = not oauth.access_token or time.time() >= oauth.token_expires_at
        return {
            "needs_registration": needs_registration,
            "needs_auth": needs_auth,
            "has_token": bool(oauth.access_token),
            "expires_at": oauth.token_expires_at,
        }

    async def _discover_capabilities(self, name: str, session: ClientSession) -> None:
        """Discover and store tools from an MCP server."""
        try:
            tools_response = await asyncio.wait_for(
                session.list_tools(),
                timeout=MCP_HTTP_DISCOVERY_TIMEOUT_SECONDS,
            )
            tools = []

            for tool in tools_response.tools:
                mcp_tool = MCPTool(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema if hasattr(tool, "inputSchema") else tool.input_schema,
                    server_name=name,
                    server_id=name,
                )
                tools.append(mcp_tool)

            self._tools[name] = tools
            log.info(f"Discovered {len(tools)} tools from MCP server '{name}'")

            # Fire tool-list-change callbacks
            for cb in self._tool_list_change_callbacks:
                try:
                    await cb(name, tools)
                except Exception:
                    pass

        except Exception as e:
            log.error("Failed to discover tools from '%s': %s", name, error_text("mcp_tool_discovery_failed", e))
            self._tools[name] = []

    def on_tool_list_change(self, callback) -> None:
        """Register a callback invoked when a server's tool list changes.

        Signature: async def callback(server_name: str, tools: list[MCPTool]) -> None
        """
        self._tool_list_change_callbacks.append(callback)

    async def refresh_tool_list(self, name: str) -> int:
        """Re-fetch the tool list from a connected server. Returns new tool count."""
        session = self._sessions.get(name)
        if not session:
            raise RuntimeError(f"Server '{name}' is not connected")
        await self._discover_capabilities(name, session)
        return len(self._tools.get(name, []))

    async def disconnect(self, name: str) -> bool:
        """Disconnect from an MCP server."""
        if name in self._sessions:
            try:
                runner = self._runners.pop(name, None)
                if runner is not None:
                    await runner.stop()
                else:
                    await self._sessions[name].close()
                del self._sessions[name]
                if name in self._tools:
                    del self._tools[name]
                if name in self._processes:
                    proc = self._processes.pop(name)
                    proc.terminate()
                    await proc.wait()
                http_context = self._http_contexts.pop(name, None)
                if http_context is not None:
                    await http_context.__aexit__(None, None, None)
                http_client = self._http_clients.pop(name, None)
                if http_client is not None:
                    await http_client.aclose()
                log.info(f"Disconnected from MCP server '{name}'")
                return True
            except Exception as e:
                log.error("Failed to disconnect from '%s': %s", name, error_text("mcp_disconnect_failed", e))
                return False
        return False

    async def is_connected(self, name: str) -> bool:
        """Check if connected to an MCP server."""
        return name in self._sessions

    def get_tools(self, name: str | None = None) -> list[MCPTool]:
        """Get tools from an MCP server or all servers."""
        if name:
            return self._tools.get(name, [])
        all_tools = []
        for tools in self._tools.values():
            all_tools.extend(tools)
        return all_tools

    def get_tools_for_llm(self, name: str | None = None) -> list[dict[str, Any]]:
        """Get tools in OpenRouter-compatible format."""
        tools = self.get_tools(name)
        return [tool.to_openrouter_format() for tool in tools]

    async def call_tool(self, name: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on an MCP server."""
        if not MCP_AVAILABLE:
            return {
                "error": "MCP package not installed",
                "mcp_server": name,
                "mcp_tool": tool_name,
                "source": "mcp",
                "error_category": "provider_failure",
                "reason": "mcp_package_not_installed",
            }

        if name not in self._sessions:
            connected = await self.connect(name)
            if not connected:
                return {
                    "error": f"Not connected to MCP server '{name}'",
                    "mcp_server": name,
                    "mcp_tool": tool_name,
                    "source": "mcp",
                    "error_category": "inactive_server",
                    "reason": "mcp_server_not_connected",
                }

        try:
            session = self._sessions[name]
            result = await session.call_tool(tool_name, arguments)

            if hasattr(result, "content"):
                return {"success": True, "content": normalize_content_items(result.content)}
            else:
                return {"success": True, "result": str(result)}

        except Exception as e:
            safe_error = safe_tool_error_message(e)
            log.error("Failed to call MCP tool '%s' on '%s': %s", tool_name, name, safe_error)
            return {
                "error": f"MCP tool execution failed: {safe_error}",
                "mcp_server": name,
                "mcp_tool": tool_name,
                "source": "mcp",
                "error_category": "provider_failure",
                "reason": "mcp_tool_exception",
            }

    async def call_tool_by_fqn(self, fqn_tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool by its fully-qualified name (mcp_{server}_{tool})."""
        if not fqn_tool_name.startswith("mcp_"):
            return {
                "error": f"Invalid MCP tool name format: {fqn_tool_name}",
                "tool_name": fqn_tool_name,
                "source": "mcp",
                "error_category": "invalid_name",
                "reason": "invalid_mcp_tool_name",
            }

        parts = fqn_tool_name.split("_", 2)
        if len(parts) < 3:
            return {
                "error": f"Invalid MCP tool name format: {fqn_tool_name}",
                "tool_name": fqn_tool_name,
                "source": "mcp",
                "error_category": "invalid_name",
                "reason": "invalid_mcp_tool_name",
            }

        server_name = parts[1]
        tool_name = parts[2]

        return await self.call_tool(server_name, tool_name, arguments)

    async def list_resources(self, name: str) -> list[MCPResource]:
        """List resources from an MCP server; an unreachable server yields ``[]``.

        A caller that writes governance state must not use this: an empty list
        here means either "nothing advertised" or "the call failed". Use
        ``catalog_discovery.discover_mcp_resources``, which says which.
        """
        return list((await discover_mcp_resources(self, name)).items)

    async def read_resource(self, name: str, uri: str) -> dict[str, Any]:
        """Read a resource from an MCP server."""
        if name not in self._sessions:
            return {"error": f"Not connected to MCP server '{name}'"}

        try:
            session = self._sessions[name]
            response = await session.read_resource(uri)

            contents = []
            for item in response.contents:
                if hasattr(item, "text"):
                    contents.append({"type": "text", "text": item.text})
                elif hasattr(item, "data"):
                    contents.append({"type": "data", "data": item.data})
                else:
                    contents.append({"type": "unknown", "content": str(item)})

            return {"success": True, "contents": contents}

        except Exception as e:
            safe_error = safe_tool_error_message(e)
            log.error("Failed to read resource '%s' from '%s': %s", uri, name, safe_error)
            return {"error": safe_error}

    async def list_prompts(self, name: str) -> list[MCPPrompt]:
        """List prompts from an MCP server; an unreachable server yields ``[]``.

        Same caveat as ``list_resources``: use
        ``catalog_discovery.discover_mcp_prompts`` when the answer decides
        governance state.
        """
        return list((await discover_mcp_prompts(self, name)).items)

    async def get_prompt(self, name: str, prompt_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Get a rendered prompt from an MCP server."""
        if name not in self._sessions:
            return {"error": f"Not connected to MCP server '{name}'"}

        try:
            session = self._sessions[name]
            response = await session.get_prompt(prompt_name, arguments)

            return {"success": True, "messages": normalize_prompt_messages(response.messages)}

        except Exception as e:
            safe_error = safe_tool_error_message(e)
            log.error("Failed to get prompt '%s' from '%s': %s", prompt_name, name, safe_error)
            return {"error": safe_error}

    async def shutdown(self) -> None:
        """Shutdown all connections."""
        for name in list(self._sessions.keys()):
            await self.disconnect(name)


mcp_client_manager = MCPClientManager()
