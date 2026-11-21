"""Approach A: lazy tool-discovery surface. A small always-on core + discovery
tools replaces the keyword-routed allowlist; long-tail tools appear only after
the model activates them via tool_schema_get."""

from __future__ import annotations

from app.agent.core.context._context_discovery_surface import discovery_tool_surface, is_discovery_mode


def test_is_discovery_mode_reads_either_source():
    assert is_discovery_mode({"tool_surface_mode": "discovery"}, {}) is True
    assert is_discovery_mode({}, {"tool_surface_mode": "discovery"}) is True
    assert is_discovery_mode({}, {}) is False
    assert is_discovery_mode(None, None) is False


def test_core_surface_is_small_and_has_discovery_tools():
    defs, names = discovery_tool_surface(
        capability_type="diagnosis", discovered_tool_names=set(), project_config={}
    )
    # Small curated surface (an order of magnitude below the full ~476 catalog).
    assert 5 <= len(names) <= 60
    assert {"tool_search", "tool_schema_get"} <= names
    assert "knowledge_search" in names  # a core knowledge tool is always on


def test_activated_long_tail_tool_joins_the_surface():
    _, base = discovery_tool_surface(
        capability_type="diagnosis", discovered_tool_names=set(), project_config={}
    )
    _, activated = discovery_tool_surface(
        capability_type="diagnosis", discovered_tool_names={"admin_list_users"}, project_config={}
    )
    assert "admin_list_users" not in base
    assert "admin_list_users" in activated


def test_connector_gated_tool_stays_hidden_without_the_connector():
    # search_confluence is a connector tool; without the connector active it must
    # not be surfaced even if the model tries to activate it.
    _, activated = discovery_tool_surface(
        capability_type="diagnosis", discovered_tool_names={"search_confluence"}, project_config={}
    )
    assert "search_confluence" not in activated
