from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.plugins.mcp.models import MCPServerConfig, TransportType
from app.services.admin.panel.admin_mcp_service import (
    serialize_mcp_server,
    validate_mcp_extension_command,
)


def test_serialize_mcp_server_redacts_extension_secrets() -> None:
    config = MCPServerConfig(
        name="context7",
        command="npx",
        args=["-y", "ctx7"],
        headers={"CONTEXT7_API_KEY": "ctx7-test-key"},
        env={"AWS_REGION": "eu-central-1", "AWS_SECRET_ACCESS_KEY": "secret-value"},
        metadata={"catalog_slug": "context7"},
    )

    result = serialize_mcp_server(config, connected=False, tool_count=0)

    assert result["headers"]["CONTEXT7_API_KEY"] == "[redacted]"
    assert result["env"]["AWS_SECRET_ACCESS_KEY"] == "[redacted]"
    assert result["env"]["AWS_REGION"] == "eu-central-1"


def test_validate_mcp_extension_command_allows_bounded_npx_command() -> None:
    config = MCPServerConfig(
        name="context7",
        command="npx",
        args=["-y", "ctx7", "library"],
        transport=TransportType.STDIO,
    )

    validate_mcp_extension_command(config)


def test_validate_mcp_extension_command_denies_shell_wrapper() -> None:
    config = MCPServerConfig(
        name="unsafe",
        command="bash",
        args=["-lc", "echo ok"],
        transport=TransportType.STDIO,
    )

    with pytest.raises(HTTPException) as exc_info:
        validate_mcp_extension_command(config)

    assert exc_info.value.status_code == 400
    assert "Shell-style MCP execution" in str(exc_info.value.detail)


def test_validate_mcp_extension_command_denies_shell_control_tokens() -> None:
    config = MCPServerConfig(
        name="unsafe",
        command="npx",
        args=["-y", "safe-package && curl https://example.test"],
        transport=TransportType.STDIO,
    )

    with pytest.raises(HTTPException) as exc_info:
        validate_mcp_extension_command(config)

    assert exc_info.value.status_code == 400
    assert "Shell control tokens" in str(exc_info.value.detail)
