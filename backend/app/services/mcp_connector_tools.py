"""Read-only connector tools on the Knowledge MCP (Confluence, Jira, ServiceNow, Kubernetes, AWS), chat gates.

Each tool runs the **same chat tool class** (``tools/confluence.py``, ``tools/jira_impl``,
``tools/connectors/servicenow.py``), so its result is the chat's, field for field. An MCP call has no
turn configuration, so the gates the chat's registry dispatch applies (``tools/registry.
_run_governed_tool_checks``) are re-applied here, in that order, on the project config a chat turn
of this user in this Workspace would build (``mcp_extra_scope.chat_tool_project_config``):

1. the connection Workspace, authorized for the user (``not_found`` otherwise);
2. the project tool policy, including connector policies' ``disabled_tools``
   (``denied`` / ``tool_denied_by_project_policy``);
3. the connector activation (``tools/visibility.connector_activation_decision``): an explicit
   deactivation is ``denied`` / ``connector_not_active``; a Workspace without the connector's
   configuration is ``needs_configuration`` / ``connector_not_configured``;
4. the project approval policy: a read the Workspace requires an approval for is ``denied`` /
   ``approval_required`` (approvals are granted in the platform, not over MCP).

The connection credentials come from that same config, exactly as in the chat: the Workspace's tool
configuration and its connector-owned fields, nothing more. Only tools whose definition metadata is
``risk: read`` without state mutation are served; a write tool is refused at import time.

The Kubernetes and AWS reads (``mcp_infra_tools``) go through the same wrapper; Kubernetes,
a built-in in the chat, gets an explicit activation over MCP, both need Workspace-owned credentials (never the
platform host's, unless an admin opted an AWS entry in), and their results carry ``content_is_data``.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import httpx

from app.tools.jira_impl._jira_query_search import SearchJiraTickets
from app.tools.jira_impl._jira_query_ticket_actions import GetJiraTicket

from ..tools.confluence import GetConfluencePage, SearchConfluence
from ..tools.connectors.servicenow import (
    GetServiceNowRecordTool,
    ListServiceNowChangesTool,
    ListServiceNowIncidentsTool,
    ListServiceNowRecordsTool,
)
from ..tools.context import ToolContext
from ..tools.definitions import get_tool_definition_metadata
from ..tools.knowledge_evidence._scope import authorized_workspace
from ..tools.knowledge_evidence.confluence_updates import ListConfluencePageUpdatesTool
from ..tools.visibility import connector_activation_decision
from .classification_tool_policy import classification_tool_decision
from .mcp_extra_scope import chat_tool_project_config, refusal
from .mcp_infra_tools import (
    AWS,
    AWS_CREDENTIALS_REQUIRED,
    AWS_READ_TOOLS,
    CREDENTIALS_REQUIRED,
    DEACTIVATED,
    KUBERNETES,
    KUBERNETES_READ_TOOLS,
    audit_platform_credentials,
    aws_activation,
    kubernetes_activation,
    uses_platform_credentials,
    with_data_notice,
)
from .named_connections.route_planner import plan_route
from .named_connections.tool_routing import routed_execute
from .policy_engine.request_principal import policy_principal_scope
from .tool_access_policy import tool_project_policy_decision
from .tool_approval_rules import tool_approval_requirement

CONNECTOR_NOT_ACTIVE = "connector_not_active"
CONNECTOR_NOT_CONFIGURED = "connector_not_configured"


def _not_active(connector: str) -> dict[str, Any]:
    return refusal("denied", CONNECTOR_NOT_ACTIVE, f"The {connector} connector is deactivated for this Workspace.")


def _not_configured(connector: str) -> dict[str, Any]:
    return refusal(
        "needs_configuration",
        CONNECTOR_NOT_CONFIGURED,
        f"This Workspace has no {connector} connection configured.",
    )


POLICY_DENIED = refusal(
    "denied", "tool_denied_by_project_policy", "The Workspace tool policy does not allow this tool."
)
APPROVAL_REQUIRED = refusal(
    "denied",
    "approval_required",
    "The Workspace approval policy requires an approval for this tool; run it in Octryx.",
)
REQUEST_FAILED = refusal("unavailable", "connector_request_failed", "The connector request failed.")
KUBERNETES_CREDENTIALS_REQUIRED = refusal(
    "needs_configuration",
    CREDENTIALS_REQUIRED,
    "Kubernetes over MCP needs this Workspace's own k8s_api_url and k8s_token, without kubeconfig or kubectl.",
)
AWS_CREDENTIALS_REQUIRED_REFUSAL = refusal(
    "needs_configuration",
    AWS_CREDENTIALS_REQUIRED,
    "AWS over MCP needs this Workspace's own access key id and secret access key or an aws_role_arn; "
    "the platform's credentials need the admin opt-in allow_platform_credentials on the AWS connector.",
)
_CREDENTIAL_REFUSALS = {
    CREDENTIALS_REQUIRED: KUBERNETES_CREDENTIALS_REQUIRED,
    AWS_CREDENTIALS_REQUIRED: AWS_CREDENTIALS_REQUIRED_REFUSAL,
}


def require_read_only(tool_name: str) -> None:
    """Refuse to serve a connector tool over MCP unless its metadata says it only reads."""
    metadata = get_tool_definition_metadata(tool_name)
    if metadata.risk != "read" or metadata.mutates_state or metadata.change_only:
        raise ValueError(f"MCP connector tools must be read-only: {tool_name}")


class McpConnectorReadTool:
    """One chat connector read tool behind the chat's dispatch gates, on the Workspace's own config."""

    def __init__(self, tool: Any, *, connector: str | None = None, activation=None, data_notice: bool = False) -> None:
        """``connector``/``activation``: an MCP-only gate (Kubernetes, a built-in in the chat; AWS credentials)."""
        self.name = str(tool.name)
        metadata = get_tool_definition_metadata(self.name)
        if not (metadata.owner_type == "connector" and metadata.connector) and not (connector and activation):
            raise ValueError(f"Not a connector tool: {self.name}")
        require_read_only(self.name)
        self.connector = metadata.connector or connector
        self._activation = activation
        self._notice = data_notice
        self._tool = tool

    def _activation_refusal(self, config: dict[str, Any]) -> dict[str, Any] | None:
        if self._activation is not None:
            reason = self._activation(config)
            if reason is None:
                return None
            if reason in _CREDENTIAL_REFUSALS:
                return dict(_CREDENTIAL_REFUSALS[reason])
            return _not_active(self.connector) if reason == DEACTIVATED else _not_configured(self.connector)
        active, reason, _ = connector_activation_decision(self.connector, config)
        if active:
            return None
        return _not_active(self.connector) if reason == DEACTIVATED else _not_configured(self.connector)

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        result = await self._execute(params, context)
        return with_data_notice(result) if self._notice else result

    async def _execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        authorized = await authorized_workspace(params, context)
        if type(authorized) is dict:
            return authorized
        config = await chat_tool_project_config(
            context.db, user_id=str(context.user_id), workspace_id=authorized.project_id
        )
        if not tool_project_policy_decision(self.name, config).allowed:
            return dict(POLICY_DENIED)
        async with policy_principal_scope(str(context.user_id or "") or None, session_id=context.session_id or None):
            classified = classification_tool_decision(self.name, config, params)  # for this caller
        if not classified.allowed:
            return refusal("denied", classified.reason, classified.message)
        # With named connections the activation and credential rule apply to the connection
        # the call runs on, after routing; without them to the Workspace's one connection.
        routed = not plan_route(self.name, params, config).passthrough
        refused = None if routed else self._activation_refusal(config)
        if refused is not None:
            return refused
        if tool_approval_requirement(self.name, config).required:
            return dict(APPROVAL_REQUIRED)

        async def run(call_params: dict, call_context: ToolContext) -> dict[str, Any]:
            connection_config = call_context.project_config
            refused = self._activation_refusal(connection_config) if routed else None
            if refused is not None:
                return refused
            if uses_platform_credentials(self.connector, connection_config):
                await audit_platform_credentials(
                    context, tool_name=self.name, workspace_id=authorized.project_id,
                    connection_id=call_context.connection_id,
                )
            return await self._tool.execute(call_params, call_context)

        try:
            # The connection of the requested scope, exactly as in the chat dispatch.
            return await routed_execute(self.name, params, replace(context, project_config=config), run)
        except httpx.HTTPError:
            # No connector URL, status text or response body reaches the MCP caller.
            return dict(REQUEST_FAILED)


def _connector_tools() -> dict[str, Any]:
    tools = [
        McpConnectorReadTool(tool)
        for tool in (
            SearchConfluence(),
            GetConfluencePage(),
            SearchJiraTickets(),
            GetJiraTicket(),
            GetServiceNowRecordTool(),
            ListServiceNowRecordsTool(),
            ListServiceNowIncidentsTool(),
            ListServiceNowChangesTool(),
        )
    ]
    tools += [
        McpConnectorReadTool(tool, connector=AWS, activation=aws_activation, data_notice=True)
        for tool in AWS_READ_TOOLS
    ]
    tools += [
        McpConnectorReadTool(tool, connector=KUBERNETES, activation=kubernetes_activation, data_notice=True)
        for tool in KUBERNETES_READ_TOOLS
    ]
    served: dict[str, Any] = {tool.name: tool for tool in tools}
    # A governed Source Sync ledger read (not a live connector call), already Workspace-scoped and
    # ACL re-checked by the chat class itself; the chat offers it without a connector gate too.
    require_read_only("list_confluence_page_updates")
    served["list_confluence_page_updates"] = ListConfluencePageUpdatesTool()
    return served


CONNECTOR_MCP_TOOLS: dict[str, Any] = _connector_tools()

__all__ = [
    "CONNECTOR_MCP_TOOLS",
    "CONNECTOR_NOT_ACTIVE",
    "CONNECTOR_NOT_CONFIGURED",
    "McpConnectorReadTool",
    "require_read_only",
]
