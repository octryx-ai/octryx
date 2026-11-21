"""Platform OAuth 2.1 authorization server (token issuer for external MCP clients)."""

from .clients import (
    OAuthClientRegistrationError,
    get_active_client,
    redirect_uri_registered,
    register_client,
    verify_client_secret,
)
from .flows import (
    OAuthFlowError,
    create_grant,
    exchange_authorization_code,
    find_reusable_grant,
    issue_authorization_code,
)
from .metadata import authorization_server_metadata, protected_resource_metadata
from .refresh import refresh_with_token, revoke_token
from .resource import (
    OAuthResourceContext,
    acceptable_mcp_audiences,
    resolve_oauth_resource_context,
)
from .tokens import mint_access_token, verify_access_token

__all__ = [
    "OAuthClientRegistrationError",
    "OAuthFlowError",
    "OAuthResourceContext",
    "acceptable_mcp_audiences",
    "authorization_server_metadata",
    "create_grant",
    "exchange_authorization_code",
    "find_reusable_grant",
    "get_active_client",
    "issue_authorization_code",
    "mint_access_token",
    "protected_resource_metadata",
    "redirect_uri_registered",
    "refresh_with_token",
    "resolve_oauth_resource_context",
    "register_client",
    "revoke_token",
    "verify_access_token",
    "verify_client_secret",
]
