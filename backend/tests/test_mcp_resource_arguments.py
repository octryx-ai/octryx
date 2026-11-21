"""Nothing raw about an MCP resource request survives outside dispatch.

A bridge-tool call is recorded before governance has decided anything, so the raw
arguments cannot be what the recorders keep. Two rules are pinned here:

- a resource is addressed by an opaque catalog identity, so a URI the model
  supplied anyway is dropped rather than persisted or echoed;
- a credential a request carries — in a URI or in a prompt argument — is removed
  before any writer sees it, including the shapes the shared secret redaction
  does not catch on its own (``postgres://`` userinfo, an object-store presign
  query).
"""

from __future__ import annotations

import json

import pytest

from app.services.mcp_resource_credentials import (
    CREDENTIAL_FINDING_QUERY,
    CREDENTIAL_FINDING_SECRET_VALUE,
    CREDENTIAL_FINDING_USERINFO,
    mcp_resource_uri_credential_finding,
)
from app.tools.argument_sanitizers import publishable_tool_arguments, publishable_tool_call_payloads
from app.tools.registry import execute_tool_with_plugins
from tests.mcp_resource_client_support import RecordingMcpResourceManager, install_mcp_manager
from tests.mcp_resource_support import (
    DOC_URI,
    GET_PROMPT_TOOL,
    LIST_RESOURCES_TOOL,
    POSTGRES_URI,
    PRESIGNED_URI,
    PROMPT,
    READ_RESOURCE_TOOL,
    SECRET_URI,
    SERVER,
    create_mcp_workspace,
    enable_binding,
    mirror_catalog,
    prompt_binding,
    resource_context,
    resource_id,
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


def test_a_read_request_keeps_only_the_opaque_identity() -> None:
    governed = publishable_tool_arguments(
        READ_RESOURCE_TOOL,
        {"server_name": SERVER, "uri": POSTGRES_URI, "resource_id": resource_id(DOC_URI), "auto_connect": True},
    )

    assert governed == {"server_name": SERVER, "resource_id": resource_id(DOC_URI)}
    assert "s3cr3t-token" not in str(governed)


def test_a_malformed_identity_is_recorded_as_a_narrow_fact() -> None:
    """A model can put anything in ``resource_id``; only a digest shape survives."""
    governed = publishable_tool_arguments(READ_RESOURCE_TOOL, {"server_name": SERVER, "resource_id": PRESIGNED_URI})

    assert governed == {"server_name": SERVER, "resource_id": "invalid_resource_id"}


def test_prompt_arguments_are_recorded_without_their_secrets() -> None:
    governed = publishable_tool_arguments(
        GET_PROMPT_TOOL,
        {
            "server_name": SERVER,
            "prompt_name": PROMPT,
            "arguments": {"topic": "react", "api_token": "s3cr3t-token", "source": POSTGRES_URI},
        },
    )

    assert governed["prompt_name"] == PROMPT
    assert governed["arguments"]["topic"] == "react"
    assert "s3cr3t-token" not in str(governed)


def test_an_unrelated_tool_is_passed_through_untouched() -> None:
    arguments = {"path": "README.md", "token": "keep-me"}

    assert publishable_tool_arguments("read_workspace_file", arguments) is arguments


def test_a_search_listing_request_is_bounded_and_secret_free() -> None:
    governed = publishable_tool_arguments(
        LIST_RESOURCES_TOOL, {"server_name": SERVER, "search": "api_key=s3cr3t-token", "extra": "dropped"}
    )

    assert governed["server_name"] == SERVER
    assert "s3cr3t-token" not in str(governed)
    assert "extra" not in governed


def test_provider_tool_call_payloads_are_projected_in_place() -> None:
    """The assistant row carries the model's own request, so it is projected too."""
    projected = publishable_tool_call_payloads(
        [
            {
                "id": "call-1",
                "function": {
                    "name": READ_RESOURCE_TOOL,
                    "arguments": json.dumps({"server_name": SERVER, "uri": POSTGRES_URI}),
                },
            },
            {"id": "call-2", "function": {"name": "read_workspace_file", "arguments": '{"path": "README.md"}'}},
        ]
    )

    assert "s3cr3t-token" not in str(projected)
    assert json.loads(projected[0]["function"]["arguments"]) == {
        "server_name": SERVER,
        "resource_id": "invalid_resource_id",
    }
    assert projected[1]["function"]["arguments"] == '{"path": "README.md"}'


@pytest.mark.asyncio
async def test_a_rendered_prompt_echoes_its_arguments_without_their_secrets(db, monkeypatch) -> None:
    """The echo is retained and shown; only the remote call gets the raw values."""
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
