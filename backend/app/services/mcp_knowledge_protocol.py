"""Native Streamable HTTP MCP adapter for read-only Knowledge tools. OAuth only; the grant is re-validated on every
token verification, so revocation cuts access immediately."""

from __future__ import annotations

import json
from contextvars import ContextVar
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.applications import Starlette

from ..config import get_settings
from ..db import async_session_factory
from .access_control import get_project_role_for_user
from .agent_board.fencing import fenced_handlers
from .agent_board.identity import request_headers
from .classification_tool_policy import classification_tool_decision
from .data_access import as_viewer
from .mcp_agent_board_tools import register_agent_board_tools
from .mcp_agent_presence_tools import register_agent_presence_tools
from .mcp_auto_session import mcp_client_name
from .mcp_code_graph_tools import register_code_graph_tools
from .mcp_extra_registration import register_extra_tools
from .mcp_governed_knowledge import SESSION_HEADER, WORKSPACE_HEADER, resolve_mcp_workspace
from .mcp_governed_knowledge_tools import mcp_caller, register_governed_knowledge_tools
from .mcp_knowledge_auth import access_token_resource
from .mcp_knowledge_calls import (
    _EXTERNAL_SESSION_TOOL_SCOPES,
    run_entity_graph_tool,
    run_external_session_tool,
)
from .mcp_knowledge_core_tools import register_core_tools
from .mcp_knowledge_instructions import _instructions_seed, serve_connection_instructions
from .mcp_knowledge_ledger_tools import register_knowledge_ledger_tools
from .mcp_knowledge_phase import outside_run_phase
from .mcp_parity_registration import register_parity_tools
from .mcp_rest_tools import register_rest_tools
from .mcp_run_work_item import call_run_bound_work_tool, run_bound_work_tool
from .mcp_seat_analysis_guard import seat_analysis_tool_guard
from .mcp_secure_work_registration import register_secure_work_tools
from .mcp_secure_work_tools import MCP_SECURE_WORK_TOOL_HANDLERS
from .mcp_session_surface import SessionSurface
from .mcp_transport_config import mcp_transport_config
from .mcp_work_access import WORK_MCP_SCOPE, run_secure_work_tool
from .mcp_work_analysis_tools import register_work_analysis_tools
from .mcp_work_claim_tools import register_work_claim_tools
from .mcp_work_handoff_tools import register_work_handoff_tools
from .named_connections.connection_gate import hidden_reason
from .oauth_provider import acceptable_mcp_audiences, resolve_oauth_resource_context
from .policy_engine.request_principal import policy_principal_scope
from .project import get_project_config
from .prompt_catalog import PromptSet, resolve_prompt_set
from .prompt_catalog.mcp_descriptions import CatalogFastMCP
from .work_role_model.grant_checks import tool_allowed, tool_refusal
from .work_role_model.surfaces import mcp_grant

KNOWLEDGE_MCP_REQUIRED_SCOPES = ["knowledge:read"]
KNOWLEDGE_MCP_MOUNT_PATH = "/api/v1/mcp/knowledge-protocol"
KNOWLEDGE_MCP_STREAMABLE_PATH = "/mcp"
_ACTING_USER: ContextVar[str | None] = ContextVar("mcp_acting_user", default=None)


class KnowledgeMcpTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        audiences = acceptable_mcp_audiences(
            mount_path=KNOWLEDGE_MCP_MOUNT_PATH,
            streamable_path=KNOWLEDGE_MCP_STREAMABLE_PATH,
        )
        async with async_session_factory() as db:
            context = await resolve_oauth_resource_context(db, token=token, audiences=audiences)
            if context is not None:
                with as_viewer(context.user_id):
                    await serve_connection_instructions(db, context.bound_project_ids, user_id=context.user_id)
        if context is None:
            return None
        return AccessToken(
            token=context.grant_id,
            client_id=context.user_id,
            scopes=list(context.scopes),
            resource=json.dumps(
                {
                    "grant_id": context.grant_id,
                    "oauth_client_id": context.oauth_client_id,
                    "bound_project_ids": list(context.bound_project_ids or []),
                }
            ),
        )


def create_knowledge_mcp_protocol_app() -> Starlette:
    return build_knowledge_mcp_server().streamable_http_app()


async def _connection_workspace(server: FastMCP, db: AsyncSession) -> str | None:
    try:
        caller = mcp_caller(server.get_context(), _authenticated_context)
    except (HTTPException, ValueError):  # no authenticated request context: global scope
        return None
    workspace = resolve_mcp_workspace(caller)
    if isinstance(workspace, str) and await get_project_role_for_user(db, caller.user_id, workspace):
        return workspace
    return None


async def _connection_prompt_set(server: FastMCP) -> PromptSet:
    with as_viewer(_connection_user(server)):
        async with async_session_factory() as db:
            workspace_id = await _connection_workspace(server, db)
            return await resolve_prompt_set(db, workspace_id=workspace_id)


def _connection_user(server: FastMCP) -> str | None:
    try:
        return str(mcp_caller(server.get_context(), _authenticated_context).user_id or "") or None
    except (HTTPException, ValueError):
        return None


async def _connection_hidden_tools(server: FastMCP, names: list[str]) -> frozenset[str]:
    # Hidden as in the chat's listing, so chat and client list the same tools; the route plan refuses the call either
    # way.
    with as_viewer(_connection_user(server)):
        async with async_session_factory() as db:
            workspace_id = await _connection_workspace(server, db)
            if workspace_id is None:
                return frozenset()
            config = await get_project_config(workspace_id, db)
            outside_phase = await outside_run_phase(server, db, workspace_id, names, _authenticated_context)
            # The person's work roles, with the chat's own filter.
            grant = await mcp_grant(db, _connection_user(server), workspace_id)
            outside_roles = frozenset(name for name in names if not tool_allowed(grant, name))
    async with policy_principal_scope(_connection_user(server)):
        return outside_phase | outside_roles | _outside_chat_visibility(names, config) | frozenset(
            name for name in names
            if not classification_tool_decision(name, config).allowed or hidden_reason(name, config) is not None)


def _outside_chat_visibility(names: list[str], config: dict[str, Any]) -> frozenset[str]:
    # A hand-written twin of a registry tool follows the chat's visibility (``tool_offer_policy``): an inactive
    # connector or the Workspace tool policy hides it here too. A tool only this server has keeps its own rules.
    from ..tools.definitions import get_all_definitions
    from .run_capability.chat_writes import is_chat_connector_write_tool
    from .tool_offer_policy import policy_visible_definitions

    registry = set(get_all_definitions())
    twins = [{"type": "function", "function": {"name": name}} for name in names if name in registry]
    context = SimpleNamespace(project_config=config, work_role_grant=None)
    visible = policy_visible_definitions(twins, context, confirmed_per_call=is_chat_connector_write_tool)
    return frozenset(name for name in names if name in registry) - {item["function"]["name"] for item in visible}


def work_role_tool_guard(inner: Any) -> Any:
    # A tool the listing hid is refused by name; nothing runs.

    async def guard(server: FastMCP, name: str, arguments: dict[str, Any], call: Any) -> Any:
        # The tool runs in the MCP session's own task, outside the HTTP request that carried the token.
        with as_viewer(_connection_user(server)):
            async with async_session_factory() as db:
                workspace_id = await _connection_workspace(server, db)
                grant = await mcp_grant(db, _connection_user(server), workspace_id)
            refusal = tool_refusal(grant, name)
            if refusal is not None:
                return CallToolResult(content=[TextContent(type="text", text=json.dumps(refusal))], isError=True)
            return await inner(server, name, arguments, call)

    return guard


def build_knowledge_mcp_server() -> CatalogFastMCP:
    settings = get_settings()
    base_url, transport_security = mcp_transport_config(
        port=settings.port, public_origin=settings.platform_public_origin
    )
    server = CatalogFastMCP(
        "octryx-knowledge",
        prompt_set_for_request=_connection_prompt_set,
        hidden_tools_for_request=_connection_hidden_tools,
        # A seat analysis session's connection runs only its analysis tools.
        tool_call_guard=work_role_tool_guard(seat_analysis_tool_guard(_authenticated_context)),
        # The registry's tools behind tool_search and tool_call, as in the chat (``mcp_session_surface``).
        bind_request=_bind_acting_user,
        session_surface=SessionSurface(_authenticated_context, lambda server: server.own_tool_names(),
                                       lambda: async_session_factory()),  # late-bound: tests replace it
        # Built once at startup with no Workspace or prompt set: the catalog seed of
        # ``knowledge.mcp.instructions``, read from its seed module (the key registry itself builds this
        # server to collect the MCP tool descriptions, so it cannot be asked here).
        instructions=_instructions_seed(),
        token_verifier=KnowledgeMcpTokenVerifier(),
        auth=AuthSettings(
            issuer_url=base_url,
            resource_server_url=f"{base_url}{KNOWLEDGE_MCP_MOUNT_PATH}{KNOWLEDGE_MCP_STREAMABLE_PATH}",
        ),
        streamable_http_path=KNOWLEDGE_MCP_STREAMABLE_PATH,
        stateless_http=True,
        json_response=True,
        transport_security=transport_security,
    )

    register_core_tools(
        server,
        call_external_session=_call_external_session_tool,
    )
    register_secure_work_tools(server, _call_secure_work_tool)
    register_agent_presence_tools(server, _authenticated_context)
    register_work_claim_tools(server, _authenticated_context)
    register_agent_board_tools(server, _authenticated_context)
    register_work_handoff_tools(server, _authenticated_context)
    register_work_analysis_tools(server, _authenticated_context)
    register_code_graph_tools(server, _call_entity_graph_tool)  # the same scope, limit and audit
    register_governed_knowledge_tools(server, _authenticated_context)
    register_knowledge_ledger_tools(server, _authenticated_context)
    register_parity_tools(server, _authenticated_context)
    register_extra_tools(server, _authenticated_context)
    register_rest_tools(server, _authenticated_context)

    return server


async def _call_external_session_tool(ctx: Context | None, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    user_id, _bound_project_ids, grant_id, scopes = _authenticated_context(ctx)
    required_scope = _EXTERNAL_SESSION_TOOL_SCOPES[tool_name]
    if required_scope not in scopes:
        raise HTTPException(status_code=403, detail=f"OAuth grant lacks required scope: {required_scope}")
    async with async_session_factory() as db:
        return await run_external_session_tool(
            db, ctx, user_id=user_id, grant_id=grant_id, tool_name=tool_name, arguments=arguments
        )


async def _call_entity_graph_tool(ctx: Context | None, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    user_id, _bound_project_ids, grant_id, scopes = _authenticated_context(ctx)
    if "knowledge:read" not in scopes:
        raise HTTPException(status_code=403, detail="OAuth grant lacks required scope: knowledge:read")
    async with async_session_factory() as db:
        return await run_entity_graph_tool(
            db, ctx, user_id=user_id, grant_id=grant_id, tool_name=tool_name, arguments=arguments
        )


async def _call_secure_work_tool(ctx: Context | None, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    user_id, _bound_project_ids, grant_id, scopes = _authenticated_context(ctx)
    if WORK_MCP_SCOPE not in scopes:
        if run_bound_work_tool(tool_name, scopes):  # the run's own Work item only (``mcp_run_work_item``)
            return await call_run_bound_work_tool(mcp_caller(ctx, _authenticated_context), tool_name, arguments)
        raise HTTPException(status_code=403, detail=f"OAuth grant lacks required scope: {WORK_MCP_SCOPE}")
    async with async_session_factory() as db:
        return await run_secure_work_tool(
            db,
            # Agent writes are fenced by work-item claims.
            handlers=fenced_handlers(MCP_SECURE_WORK_TOOL_HANDLERS, headers=request_headers(ctx)),
            user_id=user_id,
            grant_id=grant_id,
            client_name=mcp_client_name(ctx),
            tool_name=tool_name,
            arguments=arguments,
        )


async def _bind_acting_user(server: FastMCP) -> None:
    # A server runner's account acts for the person of its active turn, as on the model and git gateways
    # (``agent_gateway.identity``); without such a turn it stays itself and is a member of nothing.
    from ..models import User
    from .devices.runner_identity import is_runner_account, runner_turn_owner

    _ACTING_USER.set(None)
    try:
        ctx = server.get_context()
        user_id, bound, grant_id, _scopes = _token_identity(ctx)
    except (HTTPException, ValueError):
        return
    headers = request_headers(ctx)
    workspace = str(headers.get(WORKSPACE_HEADER) or "").strip() or (bound[0] if bound and len(bound) == 1 else "")
    with as_viewer(user_id):
        async with async_session_factory() as db:
            user = await db.get(User, user_id)
            if not is_runner_account(user):
                return
            owner = await runner_turn_owner(db, user, grant_id=grant_id or "", workspace_id=workspace,
                                            session_key=str(headers.get(SESSION_HEADER) or "").strip())
    if owner is not None:
        _ACTING_USER.set(str(owner.id))


def _authenticated_context(ctx: Context | None) -> tuple[str, list[str] | None, str | None, tuple[str, ...]]:
    user_id, bound_project_ids, grant_id, scopes = _token_identity(ctx)
    return _ACTING_USER.get() or user_id, bound_project_ids, grant_id, scopes


def _token_identity(ctx: Context | None) -> tuple[str, list[str] | None, str | None, tuple[str, ...]]:
    if ctx is None:
        raise HTTPException(status_code=401, detail="MCP request context is required")
    request = getattr(ctx.request_context, "request", None)
    scope = getattr(request, "scope", {}) if request is not None else {}
    authenticated_user = scope.get("user") if isinstance(scope, dict) else None
    access_token = getattr(authenticated_user, "access_token", None)
    if not isinstance(access_token, AccessToken):
        raise HTTPException(status_code=401, detail="MCP Bearer OAuth authentication is required")
    resource = access_token_resource(access_token.resource)
    bound = resource.get("bound_project_ids")
    bound_project_ids = [str(item) for item in bound] if isinstance(bound, list) and bound else None
    grant_id = str(resource.get("grant_id") or "").strip() or None
    scopes = tuple(str(item) for item in access_token.scopes or [])
    return access_token.client_id, bound_project_ids, grant_id, scopes
