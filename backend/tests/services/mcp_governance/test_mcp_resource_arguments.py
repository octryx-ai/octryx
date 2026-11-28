"""Nothing raw about an MCP resource request survives outside dispatch."""

from __future__ import annotations

import pytest

from app.services.mcp_governance.resource_credentials import (
    CREDENTIAL_FINDING_QUERY,
    CREDENTIAL_FINDING_SECRET_VALUE,
    CREDENTIAL_FINDING_USERINFO,
    mcp_resource_uri_credential_finding,
)
from app.tools.registry import execute_tool_with_plugins
from tests.support.mcp_resource_client_support import RecordingMcpResourceManager, install_mcp_manager
from tests.support.mcp_resource_support import (
    DOC_URI,
    GET_PROMPT_TOOL,
    POSTGRES_URI,
    PRESIGNED_URI,
    PROMPT,
    SECRET_URI,
    SERVER,
    create_mcp_workspace,
    enable_binding,
    mirror_catalog,
    prompt_binding,
    resource_context,
)


def test_credential_findings_cover_the_shapes_text_redaction_misses() -> None:
    assert mcp_resource_uri_credential_finding(SECRET_URI) == CREDENTIAL_FINDING_USERINFO
    assert mcp_resource_uri_credential_finding(POSTGRES_URI) == CREDENTIAL_FINDING_USERINFO
    assert mcp_resource_uri_credential_finding(PRESIGNED_URI) == CREDENTIAL_FINDING_QUERY
    assert mcp_resource_uri_credential_finding("https://api.example/x?access_token=abc") == CREDENTIAL_FINDING_QUERY
    assert mcp_resource_uri_credential_finding("https://x.example/?authorization=Bearer%20ab") == (
        CREDENTIAL_FINDING_QUERY
    )
    assert mcp_resource_uri_credential_finding("https://x.example/a?token=abcdefghij") == CREDENTIAL_FINDING_QUERY
    assert mcp_resource_uri_credential_finding("docs://react api_key=AbCd" + "Ef0123456789xyz") == (
        CREDENTIAL_FINDING_SECRET_VALUE
    )
    for clean in (DOC_URI, "https://docs.example/react.md", "s3://bucket/report.json?versionId=7", ""):
        assert mcp_resource_uri_credential_finding(clean) == ""














@pytest.mark.asyncio
async def test_a_rendered_prompt_echoes_its_arguments_without_their_secrets(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, prompts=[PROMPT])
    await enable_binding(db, await prompt_binding(db, workspace, PROMPT))

    result = await execute_tool_with_plugins(
        GET_PROMPT_TOOL,
        {"server_name": SERVER, "prompt_name": PROMPT, "arguments": {"topic": "react", "source": POSTGRES_URI}},
        resource_context(workspace, db),
    )

    assert result["arguments"]["topic"] == "react"
    assert "s3cr3t-token" not in str(result)
    assert manager.prompt_gets == [(SERVER, PROMPT, {"topic": "react", "source": POSTGRES_URI})]
