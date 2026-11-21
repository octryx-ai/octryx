"""Contract tests for the one Knowledge search, ``knowledge_search``: the chat and the Knowledge MCP run one
tool class with one definition."""

from __future__ import annotations

from app.services.mcp_governed_knowledge import GOVERNED_MCP_TOOLS
from app.tools.definitions import get_all_definitions
from app.tools.definitions.knowledge_evidence import KNOWLEDGE_SEARCH_DESCRIPTION
from app.tools.knowledge_evidence.search import KnowledgeSearchTool
from app.tools.registry import TOOL_REGISTRY

OLD = "knowledge_evidence_search"
NEW = "knowledge_search"


def test_the_registry_and_the_mcp_server_share_one_knowledge_search():
    definitions = get_all_definitions()
    assert OLD not in TOOL_REGISTRY and OLD not in definitions and OLD not in GOVERNED_MCP_TOOLS
    # One class for the chat and the MCP: the governed ledger search.
    assert type(TOOL_REGISTRY[NEW]) is KnowledgeSearchTool
    assert type(GOVERNED_MCP_TOOLS[NEW][0]) is KnowledgeSearchTool
    function = definitions[NEW]["function"]
    assert function["description"] == KNOWLEDGE_SEARCH_DESCRIPTION
    assert set(function["parameters"]["properties"]) == {"query", "limit", "products", "version"}
    assert function["parameters"]["required"] == ["query"]


async def test_the_mcp_knowledge_search_schema_is_the_chat_schema():
    from mcp.server.fastmcp import FastMCP

    from app.services.mcp_knowledge_ledger_tools import register_knowledge_ledger_tools

    server = FastMCP("test")
    register_knowledge_ledger_tools(server, lambda ctx: ("u", None, None, ()))
    tool = {item.name: item for item in await server.list_tools()}[NEW]
    chat = get_all_definitions()[NEW]["function"]
    assert set(tool.inputSchema["properties"]) == set(chat["parameters"]["properties"])
    assert tool.description.startswith(KNOWLEDGE_SEARCH_DESCRIPTION)


def test_the_knowledge_workflow_names_knowledge_search():
    from app.agent.core.context.turn_tool_surface import resolve_workflow_tool_surface
    from app.services.workflow_contracts.registry import get_workflow_definition

    surface = resolve_workflow_tool_surface(workflow_id="knowledge_request", workflow_contract=None)
    assert surface[0] == NEW and OLD not in surface
    assert NEW in get_workflow_definition("knowledge_request").phases[0].preferred_tools
