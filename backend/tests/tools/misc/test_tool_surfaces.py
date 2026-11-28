"""The surface table names only registry tools, each kept off one surface with its reason; everything else is served
in the chat and on the session MCP endpoint."""

from __future__ import annotations

from app.tools.definitions import get_all_definitions
from app.tools.definitions.surfaces import BOTH, CHAT_ONLY, ENGINE_NATIVE, TOOL_SURFACES, served_over_mcp, tool_surface


def test_every_surface_entry_is_a_registry_tool_with_its_reason():
    registry = set(get_all_definitions())
    assert set(TOOL_SURFACES) <= registry, sorted(set(TOOL_SURFACES) - registry)
    for name, surface in TOOL_SURFACES.items():
        assert surface.kind in {CHAT_ONLY, ENGINE_NATIVE}, name
        assert len(surface.reason) > 20, name


def test_a_tool_without_an_entry_is_served_on_both_surfaces():
    assert tool_surface("knowledge_search").kind == BOTH and served_over_mcp("knowledge_search")
    assert tool_surface("workflow_select").kind == BOTH
    assert not served_over_mcp("propose_write_plan") and not served_over_mcp("bash")


def test_no_never_served_infrastructure_tool_reaches_the_session_mcp_endpoint():
    from app.services.mcp_infra_tools import NEVER_SERVED

    assert not [name for name in NEVER_SERVED if served_over_mcp(name)]
