"""External knowledge fetch (``fetch_and_save_knowledge``): Context7, a URL, or an MCP tool.

The tool fetches and returns the content with its source; it stores nothing (``saved: false``)
despite its name. Its callers, such as the Engineering Knowledge Pack builder, turn the returned
content into pack items. MCP capability bindings and approval policies are keyed by the tool name.
"""

import hashlib
import re
from typing import Any

import httpx

from app.tools.context import ToolContext

from ...services.outbound_egress.public_web import public_web_client
from ...time_utils import utc_now_aware
from ..markup import html_to_markdown, strip_html

_MAX_FETCH_CONTENT_CHARS = 24_000
_MAX_EXCERPT_CHARS = 1_200
_CONTEXT7_SERVER = "context7"
_CONTEXT7_NOT_CONNECTED_ERROR = (
    "Context7 MCP server is not ready in the governed Workspace registry."
)


class _FetchAbortedError(Exception):
    """Abort the fetch and return this tool result payload unchanged."""

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__("knowledge fetch aborted")
        self.payload = payload


async def _connect_mcp_server(context: ToolContext, server_name: str) -> None:
    """Resolve a persisted registration and open its scoped connection.

    Only ever called *after* governance admitted a capability, so a project that
    may not use Context7 causes no Secret Reference resolution or outbound handshake.
    """
    from app.web._helpers.context_runtime import _MCP_CATALOG

    from ...plugins.mcp.client import mcp_client_manager
    from ...services.mcp_server_registry_connections import connect_mcp_server, mcp_server_is_connected
    from ...services.mcp_workspace_context import resolve_workspace_context

    workspace = resolve_workspace_context(context)
    if context.db is None or not workspace.resolved:
        raise _FetchAbortedError({"error": _CONTEXT7_NOT_CONNECTED_ERROR})
    try:
        if await mcp_server_is_connected(
            context.db,
            name=server_name,
            workspace_id=workspace.workspace_id,
            mcp_client_manager=mcp_client_manager,
        ):
            return
    except Exception as exc:
        raise _FetchAbortedError({"error": _CONTEXT7_NOT_CONNECTED_ERROR}) from exc
    try:
        await connect_mcp_server(
            context.db,
            name=server_name,
            workspace_id=workspace.workspace_id,
            catalog=_MCP_CATALOG,
            actor_user_id=context.user_id,
            mcp_client_manager=mcp_client_manager,
        )
    except Exception as exc:
        raise _FetchAbortedError({"error": _CONTEXT7_NOT_CONNECTED_ERROR}) from exc


async def _connect_context7(context: ToolContext) -> None:
    await _connect_mcp_server(context, _CONTEXT7_SERVER)


def _governed_mcp_call(tool_name: str, context: ToolContext, *, prepare_connection=None):
    """Return a call function that enforces MCP governance before every request.

    The authoritative decision stays in ``services/mcp_capability_gate``: server
    activation, the workspace capability binding, and the project approval policy
    for the capability subject. Nothing is re-implemented here, and a denied or
    approval-pending capability raises before the remote call happens, so no
    remote output can be fetched or persisted.

    ``prepare_connection`` establishes the server connection lazily, after the
    first capability was admitted and before its request. Governance therefore
    always precedes the connection, so a denied project never triggers an
    outbound connect or handshake.
    """
    connection_prepared = prepare_connection is None

    async def call(server_name: str, remote_tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        nonlocal connection_prepared
        from ...plugins.mcp.client import mcp_client_manager
        from ...services.mcp_capability_gate import enforce_remote_mcp_capability

        blocked = await enforce_remote_mcp_capability(
            dispatch_tool_name=tool_name,
            server_name=server_name,
            tool_name=remote_tool,
            arguments=arguments,
            context=context,
        )
        if blocked is not None:
            raise _FetchAbortedError(blocked)
        if not connection_prepared:
            await prepare_connection()
            connection_prepared = True
        elif prepare_connection is None:
            await _connect_mcp_server(context, server_name)
        return await mcp_client_manager.call_tool(server_name, remote_tool, arguments)

    return call


def _truncate_content(text: str, max_chars: int = _MAX_FETCH_CONTENT_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + f"\n\n[truncated — {len(text) - max_chars} chars omitted]"


async def _fetch_via_url(url: str, timeout: int = 20) -> tuple[str, str]:
    """Fetch a URL and return (title, markdown_content). Raises on failure."""
    async with public_web_client(timeout=timeout, headers={"User-Agent": "Octryx-KnowledgeBot/1.0"}) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        raw = resp.text

    # Try to extract title
    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
    title = strip_html(title_match.group(1)) if title_match else url

    # Convert to markdown if HTML, else keep as-is
    if "text/html" in resp.headers.get("content-type", ""):
        content = html_to_markdown(raw)
    else:
        content = raw

    return title.strip(), _truncate_content(content)


async def _fetch_via_context7(library: str, topic: str, call_mcp_tool) -> tuple[str, str]:
    """
    Fetch up-to-date documentation from Context7 MCP server.

    Requires Context7 to be registered as MCP server named 'context7'.
    Setup (add to MCP server config):
      name: context7
      transport: streamable-http
      url: https://mcp.context7.com/mcp

    ``call_mcp_tool`` is the governed call from ``_governed_mcp_call``: both
    remote capabilities are decided individually, with their real arguments,
    immediately before their request.

    Returns (title, content).
    """
    # Step 1: Resolve library ID
    resolve_result = await call_mcp_tool(
        _CONTEXT7_SERVER,
        "resolve-library-id",
        {"libraryName": library, "query": topic or library},
    )
    if "error" in resolve_result:
        raise RuntimeError(f"Context7 resolve-library-id failed: {resolve_result['error']}")

    # Extract library ID from response content
    content_items = resolve_result.get("content", [])
    raw_response = " ".join(item.get("text", "") for item in content_items)

    # Context7 returns the ID in JSON or plain text — extract first /xxx/xxx pattern
    lib_id_match = re.search(r"/[\w.-]+/[\w.-]+", raw_response)
    if not lib_id_match:
        raise RuntimeError(f"Could not parse library ID from Context7 response: {raw_response[:200]}")
    library_id = lib_id_match.group(0)

    # Step 2: Fetch documentation
    docs_result = await call_mcp_tool(
        _CONTEXT7_SERVER,
        "query-docs",
        {"libraryId": library_id, "query": topic or library},
    )
    if "error" in docs_result:
        raise RuntimeError(f"Context7 query-docs failed: {docs_result['error']}")

    docs_items = docs_result.get("content", [])
    docs_text = "\n\n".join(item.get("text", "") for item in docs_items)

    title = f"{library} — {topic}" if topic else library
    return title, _truncate_content(docs_text)


class FetchAndSaveKnowledgeTool:
    """Fetch up-to-date documentation from an external source and return it with its source.

    - **context7**: current library/framework docs via the Context7 MCP server (registered as the
      official remote Context7 MCP server named ``context7``).
    - **url**: any URL (HTML or plain text), converted to markdown.
    - **mcp**: one tool of any registered MCP server.

    Nothing is stored (see the module docstring).
    """

    name = "fetch_and_save_knowledge"
    description = (
        "Fetch up-to-date documentation from an external source (Context7, URL, or any MCP server) and "
        "return the content with its source_uri. Nothing is stored."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "Database session is required"}

        source = str(params.get("source") or "").strip().lower()
        query = str(params.get("query") or "").strip()
        topic = str(params.get("topic") or "").strip()

        if not source:
            return {"error": "source is required: 'context7', 'url', or 'mcp'"}
        if not query:
            return {"error": "query is required (library name, URL, or search query)"}

        # ── Fetch content ──────────────────────────────────────────────────────
        # Every remote MCP call below goes through the governed caller, so a
        # disabled, unbound, or approval-pending capability is never called,
        # never connected to, and its output is never persisted.
        try:
            if source == "context7":
                title, content = await _fetch_via_context7(
                    query,
                    topic,
                    _governed_mcp_call(
                        self.name,
                        context,
                        prepare_connection=lambda: _connect_context7(context),
                    ),
                )

            elif source == "url":
                title, content = await _fetch_via_url(query)

            elif source == "mcp":
                # Generic: call any MCP tool
                # query = "server_name/tool_name", topic = JSON args string or empty
                server_tool = query.split("/", 1)
                if len(server_tool) != 2:
                    return {"error": "For source=mcp, query must be 'server_name/tool_name'"}
                server_name, tool_name = server_tool
                import json as _json

                try:
                    tool_args = _json.loads(topic) if topic else {}
                except ValueError:
                    tool_args = {"query": topic} if topic else {}

                result = await _governed_mcp_call(self.name, context)(server_name, tool_name, tool_args)
                if "error" in result:
                    return {"error": f"MCP call failed: {result['error']}"}
                items = result.get("content", [])
                content = _truncate_content("\n\n".join(item.get("text", "") for item in items))
                title = f"{server_name}/{tool_name}"

            else:
                return {"error": f"Unknown source '{source}'. Use: context7, url, mcp"}

        except _FetchAbortedError as aborted:
            # A governance decision (or an unavailable server) is not a fetch
            # failure: return the payload unchanged so blocked_by / approval
            # metadata stays intact.
            return aborted.payload
        except httpx.HTTPError as exc:
            return {"error": f"HTTP fetch failed: {exc}"}
        except RuntimeError as exc:
            return {"error": str(exc)}
        except Exception as exc:
            return {"error": f"Fetch failed: {exc}"}

        source_uri = _source_uri(source=source, query=query, topic=topic)
        return {
            "status": "fetched",
            "saved": False,
            "title": title,
            "source": source,
            "query": query,
            "topic": topic or None,
            "source_uri": source_uri,
            "content": content,
            "content_length": len(content),
            "source_evidence": [
                {
                    "source_type": source,
                    "source_uri": source_uri,
                    "source_content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "retrieved_at": utc_now_aware().isoformat(),
                    "evidence_excerpt": content[:_MAX_EXCERPT_CHARS],
                    "title": title,
                }
            ],
        }


def _source_uri(*, source: str, query: str, topic: str) -> str:
    if source == "url":
        return query
    if source == "mcp":
        return f"mcp://{query}"
    suffix = f"/{topic}" if topic else ""
    return f"context7://{query}{suffix}"
