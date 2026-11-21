"""Bridge coverage for the governed MCP resource and prompt tools.

This suite replaces the April 2026 regression that drove the four tools through a
``ToolContext`` with ``project_config={}`` and ``db=None``. That context predated
the project MCP server-activation gate and had failed since July 2026, and it can
no longer describe the product: the tools are governed by a real Workspace
resource/prompt catalog, so they need a real workspace, a real project
config, and a database-bound context.

The tools are exercised directly here — not through the registry — which is exactly
what pins the deny-before-transport guarantee for callers outside registry
dispatch.
"""

from __future__ import annotations

import pytest

from app.services.mcp_resource_identity import MCP_RESOURCE_POLICY_NAME
from app.tools.definitions.mcp import get_mcp_definitions
from app.tools.mcp_resource_bridge import (
    GetMcpServerPromptTool,
    ListMcpServerPromptsTool,
    ListMcpServerResourcesTool,
    ReadMcpServerResourceTool,
)
from tests.mcp_resource_client_support import RecordingMcpResourceManager, install_mcp_manager
from tests.mcp_resource_support import (
    DOC_URI,
    PROMPT,
    SERVER,
    create_mcp_workspace,
    enable_binding,
    mirror_catalog,
    prompt_binding,
    read_params,
    resource_binding,
    resource_context,
    resource_id,
)


def test_mcp_definitions_include_resource_and_prompt_bridge_tools() -> None:
    definitions = get_mcp_definitions()

    assert "list_mcp_server_resources" in definitions
    assert "read_mcp_server_resource" in definitions
    assert "list_mcp_server_prompts" in definitions
    assert "get_mcp_server_prompt" in definitions


def test_catalog_served_discovery_tools_do_not_offer_a_connect_parameter() -> None:
    definitions = get_mcp_definitions()

    for name in ("list_mcp_server_resources", "list_mcp_server_prompts"):
        properties = definitions[name]["function"]["parameters"]["properties"]
        assert "auto_connect" not in properties
    for name in ("read_mcp_server_resource", "get_mcp_server_prompt"):
        assert "auto_connect" in definitions[name]["function"]["parameters"]["properties"]


def test_the_read_contract_addresses_an_opaque_identity_not_a_uri() -> None:
    """The model is never offered a URI channel, so there is none to govern."""
    parameters = get_mcp_definitions()["read_mcp_server_resource"]["function"]["parameters"]

    assert "uri" not in parameters["properties"]
    assert parameters["required"] == ["server_name", "resource_id"]


@pytest.mark.asyncio
async def test_governed_resource_and_prompt_tools_execute_via_manager(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[DOC_URI], prompts=[PROMPT])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI), risk="read")
    await enable_binding(db, await prompt_binding(db, workspace, PROMPT), risk="read")
    context = resource_context(workspace, db)

    resources_result = await ListMcpServerResourcesTool().execute({"server_name": SERVER}, context)
    read_resource_result = await ReadMcpServerResourceTool().execute(read_params(), context)
    prompts_result = await ListMcpServerPromptsTool().execute({"server_name": SERVER}, context)
    get_prompt_result = await GetMcpServerPromptTool().execute(
        {"server_name": SERVER, "prompt_name": PROMPT, "arguments": {"topic": "react"}},
        context,
    )

    assert resources_result["resources"][0]["resource_id"] == resource_id(DOC_URI)
    assert read_resource_result["contents"][0]["text"] == "# React"
    assert prompts_result["prompts"][0]["name"] == PROMPT
    assert prompts_result["prompts"][0]["arguments"] == [
        {"name": "topic", "required": True, "description": "Topic name"}
    ]
    assert get_prompt_result["messages"][0]["content"] == "Summarize react"
    assert manager.resource_reads == [(SERVER, DOC_URI)]
    assert manager.prompt_gets == [(SERVER, PROMPT, {"topic": "react"})]


@pytest.mark.asyncio
async def test_ungoverned_items_are_denied_when_the_tools_run_outside_registry_dispatch(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[DOC_URI], prompts=[PROMPT])
    context = resource_context(workspace, db)

    read_resource_result = await ReadMcpServerResourceTool().execute(read_params(), context)
    get_prompt_result = await GetMcpServerPromptTool().execute(
        {"server_name": SERVER, "prompt_name": PROMPT},
        context,
    )

    assert read_resource_result["blocked_by"] == MCP_RESOURCE_POLICY_NAME
    assert get_prompt_result["blocked_by"] == MCP_RESOURCE_POLICY_NAME
    assert manager.touched_remote is False
