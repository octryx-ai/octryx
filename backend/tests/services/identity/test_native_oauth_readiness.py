"""Native MCP discovery and RFC 8252 redirect boundary regressions."""

from unittest.mock import AsyncMock, Mock

import pytest

from app.models.security.oauth_provider import OAuthClient
from app.services.mcp_governed_knowledge import CALLER_BOUND_MCP_TOOLS, GOVERNED_MCP_TOOLS
from app.services.mcp_parity_dispatch import PARITY_MCP_TOOLS
from app.services.oauth_provider import metadata
from app.services.oauth_provider.clients import (
    OAuthClientRegistrationError,
    _validate_redirect_uri,
    redirect_uri_registered,
    register_client,
)
from app.services.security_scope_contract import allowed_api_key_scopes


@pytest.mark.parametrize("registered,requested", [
    ("http://127.0.0.1/", "http://127.0.0.1:51723/"),
    ("http://127.0.0.1:33418/", "http://127.0.0.1:51723/"),
    ("http://127.0.0.1:33418/callback/id?binding=one", "http://127.0.0.1:51723/callback/id?binding=one"),
    ("http://[::1]/callback", "http://[::1]:51723/callback"),
    ("http://[::1]:33418/callback", "http://[::1]:51723/callback"),
    ("https://vscode.dev/redirect", "https://vscode.dev/redirect"),
    ("http://localhost:33418/callback", "http://localhost:33418/callback"),
])
def test_only_native_literal_loopback_ports_may_vary(registered, requested):
    assert redirect_uri_registered(OAuthClient(redirect_uris=[registered]), requested)


@pytest.mark.parametrize("registered,requested", [
    ("http://127.0.0.1/", "http://127.0.0.1:51723/callback"),
    ("http://127.0.0.1/callback", "http://127.0.0.1:51723/callback/"),
    ("http://127.0.0.1/callback", "http://127.0.0.1:51723/%63allback"),
    ("http://127.0.0.1/callback?a=1", "http://127.0.0.1:51723/callback?a=2"),
    ("http://127.0.0.1/callback?a=1&b=2", "http://127.0.0.1:51723/callback?b=2&a=1"),
    ("http://127.0.0.1/callback", "http://127.0.0.1:51723/callback?"),
    ("http://127.0.0.1/callback", "https://127.0.0.1:51723/callback"),
    ("http://127.0.0.1/callback", "http://[::1]:51723/callback"),
    ("http://127.0.0.1/callback", "http://localhost:51723/callback"),
    ("http://localhost:33418/callback", "http://localhost:51723/callback"),
    ("https://127.0.0.1:33418/callback", "https://127.0.0.1:51723/callback"),
    ("https://example.com:33418/callback", "https://example.com:51723/callback"),
    ("http://127.0.0.1/callback", "http://127.0.0.2:51723/callback"),
    ("http://127.0.0.1/callback", "http://127.0.0.1.evil.test:51723/callback"),
    ("http://[::1]/callback", "http://[0:0:0:0:0:0:0:1]:51723/callback"),
    ("http://127.0.0.1/callback", "HTTP://127.0.0.1:51723/callback"),
])
def test_redirect_port_exception_preserves_every_other_component(registered, requested):
    assert not redirect_uri_registered(OAuthClient(redirect_uris=[registered]), requested)


INVALID_URIS = [
    "http://user:private@127.0.0.1:33418/callback",
    "http://@127.0.0.1:33418/callback",
    "https://user:private@example.com/callback",
    "http://127.0.0.1/callback#fragment",
    "http://127.0.0.1/callback#",
    "https://example.com/callback#fragment",
    "http://127.0.0.1:invalid/callback",
    "http://127.0.0.1:65536/callback",
    "http://127.0.0.1:-1/callback",
    "http://127.0.0.1:0/callback",
    "http://127.0.0.1:/callback",
    "http://[::1/callback",
    "http://[::1]evil/callback",
    "http://[::1]evil:33418/callback",
    "https://example.com:invalid/callback",
    "https:///callback",
    "http://evil.test/callback",
    "vscode://dynamicauthprovider/redirect",
    "http://127.0.0.1/call\nback",
]


@pytest.mark.parametrize("uri", INVALID_URIS)
def test_registration_rejects_invalid_redirects_without_echoing_credentials(uri):
    with pytest.raises(OAuthClientRegistrationError) as error:
        _validate_redirect_uri(uri)
    assert "private" not in str(error.value)


@pytest.mark.parametrize("uri", INVALID_URIS)
def test_matching_revalidates_both_request_and_stored_registration(uri):
    valid = "http://127.0.0.1:33418/callback"
    assert not redirect_uri_registered(OAuthClient(redirect_uris=[valid]), uri)
    assert not redirect_uri_registered(OAuthClient(redirect_uris=[uri]), valid)
    assert not redirect_uri_registered(OAuthClient(redirect_uris=[uri]), uri)


def test_resource_read_scopes_prevent_broad_authorization_server_fallback():
    resource = metadata.protected_resource_metadata("https://platform.example", resource_url="https://platform.example/mcp")
    authority = metadata.authorization_server_metadata("https://platform.example")
    assert metadata.READ_CONTEXT_SCOPES == ("knowledge:read", "workflow:read")
    assert resource["scopes_supported"] == list(metadata.READ_CONTEXT_SCOPES)
    assert authority["scopes_supported"] == sorted(allowed_api_key_scopes())
    # Native VS Code chooses resource scopes before its broad authorization-server fallback.
    assert (resource.get("scopes_supported") or authority["scopes_supported"]) == ["knowledge:read", "workflow:read"]
    resource["scopes_supported"].append("admin")
    assert metadata.protected_resource_metadata("https://platform.example", resource_url="mcp")["scopes_supported"] == [
        "knowledge:read", "workflow:read",
    ]


def test_advertised_read_pair_matches_actual_six_tool_gates():
    requirements = {
        GOVERNED_MCP_TOOLS[name][1] for name in ("knowledge_search", "knowledge_read", "knowledge_changes")
    }
    requirements.add(CALLER_BOUND_MCP_TOOLS["knowledge_code_impact"][1])
    requirements.update(PARITY_MCP_TOOLS[name][1] for name in ("workflow_catalog", "workflow_run_status"))
    assert requirements == set(metadata.READ_CONTEXT_SCOPES)


@pytest.mark.asyncio
async def test_explicit_broader_client_registration_keeps_its_requested_scopes():
    db = Mock(commit=AsyncMock())
    requested = "knowledge:read knowledge:write workflow:execute model:invoke"
    result = await register_client(db, payload={
        "client_name": "explicit-existing-client",
        "redirect_uris": ["https://client.example/callback"],
        "scope": requested,
    })
    assert result["scope"] == requested
    assert db.add.call_args.args[0].scopes == requested.split()
    db.commit.assert_awaited_once()
