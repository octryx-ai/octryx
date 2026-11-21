"""Tool descriptions are prompt catalog data: chat tool schemas and the Knowledge MCP.

Golden: every built-in tool's description and parameter descriptions resolve, from their seed,
to the code definition, and the Knowledge MCP serves its code descriptions unchanged. Edits:
literal keys keep braces verbatim; an unknown tool key is refused; a published Workspace edit
changes the next chat turn's offered schema (recorded on the trace) and the next MCP
``tools/list`` / ``initialize`` of a connection to that Workspace.
"""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import select

from app.models import TurnTrace, User
from app.services.prompt_catalog import lifecycle, prompt_set_scope, resolve_prompt_set, seed_prompt_set
from app.services.prompt_catalog.mcp_descriptions import catalog_mcp_tools, mcp_description_key
from app.services.prompt_catalog.registry import prompt_key_registry
from app.services.prompt_catalog.store import add_version, create_template
from app.services.prompt_catalog.tool_catalog import iter_param_descriptions, tool_description_key, tool_param_key
from app.services.prompt_catalog.tool_descriptions import (
    CITATION_RULE,
    apply_tool_descriptions,
    catalog_tool_descriptions,
)
from app.tools.definitions import get_all_definitions
from app.tools.definitions.knowledge_evidence import KNOWLEDGE_SEARCH_DESCRIPTION
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.mcp_native_support import mcp_request, native_token, session_factory
from tests.product_run_chat_binding_support import FINAL_RESPONSE, _session, _turn
from tests.product_run_chat_support import world  # noqa: F401 - fixture
from tests.prompt_catalog_publish_support import publish_reviewed

SCOPES = ["knowledge:read", "knowledge:write"]


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _publish_direct(db, key: str, body: str, *, scope_type: str = "global", scope_id: str | None = None) -> None:
    """A published version without the four-eyes round trip (covered in test_prompt_catalog_contract)."""
    admin = await _admin(db)
    template = await create_template(db, key=key, scope_type=scope_type, scope_id=scope_id, created_by=admin.id)
    await add_version(
        db, template=template, body=body, source="admin", state="published", created_by=admin.id, change_note=""
    )


def test_every_built_in_tool_description_resolves_from_its_seed_to_the_code_definition() -> None:
    registry = prompt_key_registry()
    definitions = get_all_definitions()
    prompt_set = seed_prompt_set()
    for name, definition in definitions.items():
        function = definition["function"]
        assert prompt_set.render(tool_description_key(name)) == function["description"], name
        for path, prop in iter_param_descriptions(function.get("parameters")):
            if prop["description"]:
                assert registry[tool_param_key(name, path)].seed == prop["description"], (name, path)
    assert {spec.area for key, spec in registry.items() if key.startswith("tool.")} == {"tool"}
    assert all(spec.literal for key, spec in registry.items() if key.startswith(("tool.", "mcp.")))
    original = copy.deepcopy(list(definitions.values()))
    with prompt_set_scope(prompt_set):
        served = catalog_tool_descriptions(list(definitions.values()))
    assert served == original


async def test_the_knowledge_mcp_serves_its_code_descriptions_from_the_seed() -> None:
    from app.services.mcp_knowledge_protocol import build_knowledge_mcp_server

    server = build_knowledge_mcp_server()
    tools = server._tool_manager.list_tools()
    code = {tool.name: tool.description for tool in tools}
    listed = [tool for tool in await server.list_tools()]  # no request: global scope, nothing published
    assert {tool.name: tool.description for tool in listed} == code
    assert code["knowledge_search"].startswith(KNOWLEDGE_SEARCH_DESCRIPTION)
    assert {mcp_description_key(name) for name in code if code[name]} <= set(prompt_key_registry())


async def test_literal_keys_keep_braces_and_unknown_tool_keys_are_refused(db) -> None:
    admin = await _admin(db)
    key = tool_param_key("knowledge_search", ("query",))
    body = 'Terms to search for, e.g. {"query": "spring {boot}"}.'
    await publish_reviewed(db, key, body)
    prompt_set = await resolve_prompt_set(db, workspace_id=None)

    served = apply_tool_descriptions(prompt_set, get_all_definitions()["knowledge_search"])
    assert served["function"]["parameters"]["properties"]["query"]["description"] == body
    assert prompt_set.usage()[key]["source"] == "global"
    with pytest.raises(ValueError):
        prompt_set.render(key, query="x")
    with pytest.raises(lifecycle.PromptCatalogRefusal) as refused:
        await lifecycle.create_draft(
            db, key="tool.no_such_tool.description", scope_type="global", scope_id=None,
            body="x", change_note="", user=admin,
        )
    assert (refused.value.code, refused.value.status) == ("prompt_key_not_found", 404)


@pytest.mark.asyncio
async def test_a_published_workspace_tool_description_reaches_the_next_turn_schema(db, world, monkeypatch) -> None:  # noqa: F811
    import app.agent.engine as engine_module
    import app.agent.providers as providers_module

    session = await _session(db)
    offered: list[str] = []

    def capturing_provider(**_kwargs):
        class _Provider:
            async def chat(self, messages, model=None, tools=None, **_ignored):
                offered.extend(item["function"]["description"] for item in tools or [])
                return {**FINAL_RESPONSE, "model": model or ""}

            async def close(self):
                return None

        return _Provider()

    monkeypatch.setattr(providers_module, "get_provider", capturing_provider)
    monkeypatch.setattr(engine_module, "get_provider", capturing_provider)
    key = tool_description_key("get_current_time")
    await _publish_direct(db, key, "Workspace wording of the clock tool.", scope_type="workspace",
                          scope_id=session.project_id)
    await db.commit()

    async for _event in _turn(db, session):
        pass

    assert offered == ["Workspace wording of the clock tool."]
    trace = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session.id))).scalars().first()
    used = trace.context_snapshot_json["prompt_templates"]["used"]
    assert used[key]["source"] == "workspace" and used[key]["ref"] == f"{key}@1"


async def test_mcp_tools_list_and_initialize_serve_the_connection_workspace_edits(db, monkeypatch) -> None:
    from app.services import mcp_governed_knowledge_tools, mcp_knowledge_ledger_tools, mcp_knowledge_protocol

    factory = session_factory(db)
    for module in (mcp_knowledge_protocol, mcp_governed_knowledge_tools, mcp_knowledge_ledger_tools):
        monkeypatch.setattr(module, "async_session_factory", factory)
    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    outsider_id = await seed_member(db, workspace_id=await seed_workspace(db), role="member")
    rule = "Cite only what a passage says (workspace wording)."
    await _publish_direct(db, "evidence.citation_rule", rule, scope_type="workspace", scope_id=workspace_id)
    await _publish_direct(db, mcp_description_key("knowledge_read"), "Read one passage (workspace wording).",
                          scope_type="workspace", scope_id=workspace_id)
    await _publish_direct(db, "knowledge.mcp.instructions", "Workspace MCP instructions.",
                          scope_type="workspace", scope_id=workspace_id)
    await db.commit()
    headers = {"X-Octryx-Workspace": workspace_id}

    member = await native_token(db, user_id=member_id, scopes=SCOPES)
    tools = {tool["name"]: tool for tool in (await mcp_request(member, "tools/list", headers=headers))["result"]["tools"]}
    assert tools["knowledge_read"]["description"] == "Read one passage (workspace wording)."
    search = tools["knowledge_search"]["description"]
    assert search.startswith(KNOWLEDGE_SEARCH_DESCRIPTION[: -len(CITATION_RULE)] + rule)
    assert CITATION_RULE not in search

    outsider = await native_token(db, user_id=outsider_id, scopes=SCOPES)
    outside = {
        tool["name"]: tool["description"]
        for tool in (await mcp_request(outsider, "tools/list", headers=headers))["result"]["tools"]
    }
    assert outside["knowledge_search"].startswith(KNOWLEDGE_SEARCH_DESCRIPTION)  # not a member: global scope

    bound = await native_token(db, user_id=member_id, scopes=SCOPES, project_ids=[workspace_id])
    initialized = await mcp_request(
        bound,
        "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
    )
    assert initialized["result"]["instructions"] == "Workspace MCP instructions."


def test_catalog_mcp_tools_leaves_unedited_tools_untouched() -> None:
    from mcp.types import Tool as MCPTool

    tool = MCPTool(name="knowledge_projects", description="List projects.", inputSchema={"type": "object"})
    assert catalog_mcp_tools(seed_prompt_set(), [tool])[0] is tool
