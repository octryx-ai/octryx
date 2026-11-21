"""Shared Microsoft Graph helpers for connector tools."""

from __future__ import annotations

from app.services.outbound_egress import CONNECTION_MICROSOFT_GRAPH

from ..context import ToolContext
from .common import _string, connection_http_form_json

#: This module's HTTP helpers use the microsoft_graph egress rule.
_http_form_json = connection_http_form_json(CONNECTION_MICROSOFT_GRAPH)


async def _microsoft_graph_token(context: ToolContext, *, scope: str) -> str:
    direct_token = _string(
        context.project_config.get("microsoft_graph_access_token")
        or context.project_config.get("outlook_access_token")
        or context.project_config.get("sharepoint_access_token")
        or context.project_config.get("azure_access_token")
    )
    if direct_token:
        return direct_token
    tenant_id = _string(
        context.project_config.get("outlook_tenant_id")
        or context.project_config.get("sharepoint_tenant_id")
        or context.project_config.get("azure_tenant_id")
    )
    client_id = _string(
        context.project_config.get("outlook_client_id")
        or context.project_config.get("sharepoint_client_id")
        or context.project_config.get("azure_client_id")
    )
    client_secret = _string(
        context.project_config.get("outlook_client_secret")
        or context.project_config.get("sharepoint_client_secret")
        or context.project_config.get("azure_client_secret")
    )
    if not tenant_id or not client_id or not client_secret:
        raise ValueError("Connector credentials are incomplete")
    data = await _http_form_json(
        "POST",
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        form_data={
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": scope,
            "grant_type": "client_credentials",
        },
    )
    token = _string(data.get("access_token"))
    if not token:
        raise ValueError("Failed to obtain Microsoft access token")
    return token
