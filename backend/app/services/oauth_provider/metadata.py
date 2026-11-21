"""RFC 8414 / RFC 9728 metadata documents for the OAuth authorization server."""

from __future__ import annotations

from typing import Any

from ..security_scope_contract import allowed_api_key_scopes

READ_CONTEXT_SCOPES = ("knowledge:read", "workflow:read")


def authorization_server_metadata(issuer: str) -> dict[str, Any]:
    """RFC 8414 document served at /.well-known/oauth-authorization-server."""
    base = issuer.rstrip("/")
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "revocation_endpoint": f"{base}/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "scopes_supported": sorted(allowed_api_key_scopes()),
    }


def protected_resource_metadata(issuer: str, *, resource_url: str) -> dict[str, Any]:
    """RFC 9728 document for the MCP resource server endpoint."""
    return {
        "resource": resource_url,
        "authorization_servers": [issuer.rstrip("/")],
        "bearer_methods_supported": ["header"],
        # Native clients prefer this resource's read scopes over the full AS universe.
        "scopes_supported": list(READ_CONTEXT_SCOPES),
    }
