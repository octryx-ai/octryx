"""Governed MCP resource and prompt bridge tools."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ..services.mcp_access_policy import blocked_mcp_server_result, mcp_access_for_context
from ..services.mcp_governance.resource_arguments import MCP_RESOURCE_ID_PARAM, governed_argument_value
from ..services.mcp_governance.resource_audit import (
    GOVERNANCE_AUDIT_KEY,
    GOVERNANCE_AUDIT_UNAVAILABLE,
    OUTCOME_EXECUTED,
    OUTCOME_TRANSPORT_FAILED,
    OUTCOME_TRANSPORT_UNAVAILABLE,
)
from ..services.mcp_governance.resource_identity import (
    MCP_PROMPT_KIND,
    MCP_RESOURCE_KIND,
    normalized_mcp_prompt_identity,
    normalized_mcp_resource_identity,
)
from .context import ToolContext


def _server_denial(server_name: str, context: ToolContext) -> dict[str, Any] | None:
    decision = mcp_access_for_context(server_name, context)
    return None if decision.allowed else blocked_mcp_server_result(decision)


async def _configured_server_names(context: ToolContext) -> list[str]:
    if context.db is None:
        return []
    from ..services.mcp_server_registry_queries import list_scoped_registration_names
    from ..services.mcp_workspace_context import resolve_workspace_context

    workspace = resolve_workspace_context(context)
    if not workspace.resolved:
        return []
    return await list_scoped_registration_names(context.db, workspace_id=workspace.workspace_id)


async def _connect_registry_server(server_name: str, context: ToolContext, manager: Any) -> bool:
    if context.db is None:
        return False
    from app.web._helpers.context_runtime import _MCP_CATALOG

    from ..services.mcp_server_registry_connections import connect_mcp_server
    from ..services.mcp_workspace_context import resolve_workspace_context

    workspace = resolve_workspace_context(context)
    if not workspace.resolved:
        return False
    try:
        await connect_mcp_server(
            context.db,
            name=server_name,
            workspace_id=workspace.workspace_id,
            catalog=_MCP_CATALOG,
            actor_user_id=context.user_id,
            mcp_client_manager=manager,
        )
    except HTTPException:
        return False
    return True


async def _registry_server_connected(server_name: str, context: ToolContext, manager: Any) -> bool:
    if context.db is None:
        return False
    from ..services.mcp_server_registry_connections import mcp_server_is_connected
    from ..services.mcp_workspace_context import resolve_workspace_context

    workspace = resolve_workspace_context(context)
    if not workspace.resolved:
        return False
    try:
        return await mcp_server_is_connected(
            context.db,
            name=server_name,
            workspace_id=workspace.workspace_id,
            mcp_client_manager=manager,
        )
    except HTTPException:
        return False


def _transport_outcome(result: Any) -> str:
    if isinstance(result, dict) and result.get("error") is not None:
        return OUTCOME_TRANSPORT_FAILED
    return OUTCOME_EXECUTED


def _matches(search: str, *values: Any) -> bool:
    if not search:
        return True
    return any(search in str(value or "").lower() for value in values)


def _governance_payload(listing: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "state": listing.state,
        # Named so an empty listing can never be read as "the server has nothing":
        # discovery ran against the Workspace catalog, not against the server.
        "source": "workspace_catalog",
        "catalog_entries": listing.catalog_entries,
        "visible": len(listing.visible),
    }
    if not listing.audit_recorded:
        payload[GOVERNANCE_AUDIT_KEY] = GOVERNANCE_AUDIT_UNAVAILABLE
    return payload


class ListMcpServerResourcesTool:
    name = "list_mcp_server_resources"
    description = "List the MCP resources this workspace governs for one server, without reading them."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        server_name = str(params.get("server_name") or "").strip()
        if not server_name:
            return {"error": "server_name is required"}
        server_denial = _server_denial(server_name, context)
        if server_denial is not None:
            return server_denial

        # Imported lazily: the gate reaches the approval gate, whose import chain
        # must not run while the tool registry is being built.
        from ..services.mcp_governance.resource_discovery import governed_mcp_resource_listing

        listing = await governed_mcp_resource_listing(
            context,
            kind=MCP_RESOURCE_KIND,
            server_name=server_name,
            tool_name=self.name,
        )
        if listing.blocked_result is not None:
            return {"server_name": server_name, **listing.blocked_result}

        search = str(params.get("search") or "").strip().lower()
        resources = []
        for entry, decision, approval_required in listing.visible:
            contract = entry.contract
            name = str(contract.get("name") or "")
            description = str(contract.get("description") or "")
            if not _matches(search, entry.identity, name, description):
                continue
            resources.append(
                {
                    # The only addressable form. The governed URI stays in the
                    # Workspace catalog, where an administrator can read it.
                    MCP_RESOURCE_ID_PARAM: entry.identity,
                    "name": name,
                    "description": description,
                    "mime_type": str(contract.get("mimeType") or "") or None,
                    "risk": decision.risk,
                    "approval_required": approval_required,
                }
            )
        return {
            "server_name": server_name,
            "search": search,
            "count": len(resources),
            "resources": resources,
            "resource_governance": _governance_payload(listing),
        }


class ReadMcpServerResourceTool:
    name = "read_mcp_server_resource"
    description = "Read one governed MCP resource from a server by its governed catalog identity."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ..plugins.mcp.client import mcp_client_manager

        server_name = str(params.get("server_name") or "").strip()
        resource_id = normalized_mcp_resource_identity(params.get(MCP_RESOURCE_ID_PARAM))
        if not server_name:
            return {"error": "server_name is required"}
        server_denial = _server_denial(server_name, context)
        if server_denial is not None:
            return server_denial

        from ..services.mcp_governance.resource_access import (
            governed_mcp_resource_access,
            record_mcp_resource_execution,
        )
        from ..services.mcp_governance.resource_gate import annotate_lost_governance_audit

        access = await governed_mcp_resource_access(
            context,
            kind=MCP_RESOURCE_KIND,
            server_name=server_name,
            identity=resource_id,
            tool_name=self.name,
            configured_server_names=await _configured_server_names(context),
        )
        if access.blocked_result is not None:
            # Denied or held before any connection: no handshake, no read, and
            # the refusal is already the audited final outcome.
            return access.blocked_result

        # One authoritative server identity: governance resolved which configured
        # server owns this catalog entry, and that is the name the transport gets.
        target = access.canonical_server_name
        connected = await _registry_server_connected(target, context, mcp_client_manager)
        if not connected and bool(params.get("auto_connect", True)):
            connected = await _connect_registry_server(target, context, mcp_client_manager)
        if not connected:
            recorded = await record_mcp_resource_execution(
                context, access, tool_name=self.name, outcome=OUTCOME_TRANSPORT_UNAVAILABLE
            )
            return annotate_lost_governance_audit({"error": f"MCP server '{target}' is not connected"}, recorded)

        # The catalog's governed URI is what reaches the transport; the model
        # never supplied one and never sees one.
        try:
            result = await mcp_client_manager.read_resource(target, access.governed_identity)
        except Exception:
            # The provider failure keeps its own typing further up; what this
            # owner must not do is leave the request recorded as an execution.
            await record_mcp_resource_execution(
                context, access, tool_name=self.name, outcome=OUTCOME_TRANSPORT_FAILED
            )
            raise
        recorded = await record_mcp_resource_execution(
            context, access, tool_name=self.name, outcome=_transport_outcome(result)
        )
        payload: dict[str, Any] = {"server_name": target, MCP_RESOURCE_ID_PARAM: resource_id}
        if isinstance(result, dict):
            return annotate_lost_governance_audit({**payload, **result}, recorded)
        return annotate_lost_governance_audit({**payload, "result": result}, recorded)


class ListMcpServerPromptsTool:
    name = "list_mcp_server_prompts"
    description = "List the MCP prompts this workspace governs for one server, without rendering them."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        server_name = str(params.get("server_name") or "").strip()
        if not server_name:
            return {"error": "server_name is required"}
        server_denial = _server_denial(server_name, context)
        if server_denial is not None:
            return server_denial

        from ..services.mcp_governance.resource_discovery import governed_mcp_resource_listing

        listing = await governed_mcp_resource_listing(
            context,
            kind=MCP_PROMPT_KIND,
            server_name=server_name,
            tool_name=self.name,
        )
        if listing.blocked_result is not None:
            return {"server_name": server_name, **listing.blocked_result}

        search = str(params.get("search") or "").strip().lower()
        prompts = []
        for entry, decision, approval_required in listing.visible:
            contract = entry.contract
            description = str(contract.get("description") or "")
            if not _matches(search, entry.identity, description):
                continue
            arguments = contract.get("arguments")
            prompts.append(
                {
                    "name": entry.identity,
                    "description": description,
                    "arguments": arguments if isinstance(arguments, list) else [],
                    "risk": decision.risk,
                    "approval_required": approval_required,
                }
            )
        return {
            "server_name": server_name,
            "search": search,
            "count": len(prompts),
            "prompts": prompts,
            "prompt_governance": _governance_payload(listing),
        }


class GetMcpServerPromptTool:
    name = "get_mcp_server_prompt"
    description = "Render one governed MCP prompt from a server by prompt name."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ..plugins.mcp.client import mcp_client_manager

        server_name = str(params.get("server_name") or "").strip()
        # Bounded at ingest, like ``resource_id``: a name longer than the catalog
        # can key is not an identity, and denies exactly as an unknown one does.
        prompt_name = normalized_mcp_prompt_identity(params.get("prompt_name"))
        if not server_name:
            return {"error": "server_name is required"}
        server_denial = _server_denial(server_name, context)
        if server_denial is not None:
            return server_denial

        from ..services.mcp_governance.resource_access import (
            governed_mcp_resource_access,
            record_mcp_resource_execution,
        )
        from ..services.mcp_governance.resource_gate import annotate_lost_governance_audit

        raw_arguments = params.get("arguments")
        arguments = raw_arguments if isinstance(raw_arguments, dict) else {}
        access = await governed_mcp_resource_access(
            context,
            kind=MCP_PROMPT_KIND,
            server_name=server_name,
            identity=prompt_name,
            tool_name=self.name,
            configured_server_names=await _configured_server_names(context),
            arguments=arguments,
        )
        if access.blocked_result is not None:
            return access.blocked_result

        target = access.canonical_server_name
        connected = await _registry_server_connected(target, context, mcp_client_manager)
        if not connected and bool(params.get("auto_connect", True)):
            connected = await _connect_registry_server(target, context, mcp_client_manager)
        if not connected:
            recorded = await record_mcp_resource_execution(
                context, access, tool_name=self.name, outcome=OUTCOME_TRANSPORT_UNAVAILABLE
            )
            return annotate_lost_governance_audit({"error": f"MCP server '{target}' is not connected"}, recorded)

        try:
            result = await mcp_client_manager.get_prompt(target, access.governed_identity, arguments)
        except Exception:
            await record_mcp_resource_execution(
                context, access, tool_name=self.name, outcome=OUTCOME_TRANSPORT_FAILED
            )
            raise
        recorded = await record_mcp_resource_execution(
            context, access, tool_name=self.name, outcome=_transport_outcome(result)
        )
        payload: dict[str, Any] = {
            "server_name": target,
            "prompt_name": access.governed_identity,
            # The echo is retained and shown; only the remote call gets the raw
            # argument values.
            "arguments": governed_argument_value(arguments),
        }
        if isinstance(result, dict):
            return annotate_lost_governance_audit({**payload, **result}, recorded)
        return annotate_lost_governance_audit({**payload, "result": result}, recorded)


__all__ = [
    "GetMcpServerPromptTool",
    "ListMcpServerPromptsTool",
    "ListMcpServerResourcesTool",
    "ReadMcpServerResourceTool",
]
