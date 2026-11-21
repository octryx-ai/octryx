"""The chat offers what the Octryx client's MCP server offers.

A person can work through the chat as through the client: the chat offers the client's tools, and like the
client it sends only its core tools in full and the rest by name (``tool_search`` loads them; this keeps cheap
and weak models usable). Connector visibility still hides a connector's tools until the Workspace activates it.
"""

from __future__ import annotations

import json

import pytest

from app.agent.core.context.context_planner import plan_turn_context
from app.agent.core.context.run_context_tooling import build_run_context_tool_definitions
from app.agent.core.context.turn_tool_surface import resolve_turn_tool_surface
from app.agent.engine.messages._engine_message_helpers import _exclude_tool_definitions, _filter_tool_definitions
from app.services.chat_deferred_tools import (
    CHAT_CORE_TOOLS,
    defer_chat_tools,
    sent_chat_tool_definitions,
    session_loaded_tool_names,
)
from app.services.governed_default_tool_sets import governed_default_tool_set
from app.services.tool_surface_budget_policy import budget_tool_definitions_for_runtime
from app.tools.context import ToolContext
from app.tools.registry import get_all_tools_with_plugins
from tests.chat_client_parity_support import ACTIVE, CHAT_STATE, chat_context  # noqa: F401

# Connector read tools must be available consistently to the chat and MCP client.
CLIENT_READS = {
    "k8s": {"list_k8s_pods", "describe_k8s_pod", "get_k8s_deployments", "list_k8s_nodes"},
    "aws": {"list_aws_ec2_instances", "aws_topology_snapshot"},
    "servicenow": {"get_servicenow_record", "list_servicenow_incidents", "list_servicenow_changes"},
    "platform": {"graph_neighbors", "config_vs_manual", "ops_chain", "create_diagram", "edit_diagram"},
}


def _plan(project_config: dict):
    plan = plan_turn_context(project_id="p1", agent_definition=None, session_metadata={}, history_count=0)
    return resolve_turn_tool_surface(plan, capability_type="diagnosis", workflow_id=None, workflow_contract=None,
                                     routing_resolution=None, agent_definition=None, project_config=project_config,
                                     capability_class="read_only", chat_connector_writes=True)


async def _offered_definitions(project_config: dict) -> tuple[list[dict], ToolContext]:
    plan = _plan(project_config)
    context = ToolContext(user_id="u1", project_ids=[], roles=["member"], session_id="s1",
                          project_config=dict(project_config), capability_type="diagnosis",
                          run_capability=dict(CHAT_STATE))
    definitions = await build_run_context_tool_definitions(
        db=None, tool_context=context, capability_type="diagnosis", include_tools=plan.include_tools,
        tool_allowlist=plan.tool_allowlist, blocked_tools=plan.blocked_tools, agent_definition=None,
        get_all_tools_with_plugins=get_all_tools_with_plugins, filter_tool_definitions=_filter_tool_definitions,
        exclude_tool_definitions=_exclude_tool_definitions)
    return definitions, context


async def _offered(project_config: dict) -> set[str]:
    definitions, _context = await _offered_definitions(project_config)
    return {definition["function"]["name"] for definition in definitions}


class _Message:
    def __init__(self, *calls: tuple[str, dict]):
        self.tool_calls = [{"function": {"name": name, "arguments": json.dumps(args)}} for name, args in calls]


def test_the_chat_set_carries_the_clients_tools_and_tool_search():
    tools = set(governed_default_tool_set("diagnosis").tools)
    assert set().union(*CLIENT_READS.values()) | {"tool_search", "work_item_transition"} <= tools
    # propose_write_plan comes with the chat's writes (turn_tool_surface._chat_surface), not with the governed set.
    # The core's connector writes come with the chat's writes too (turn_tool_surface._chat_surface).
    assert set(CHAT_CORE_TOOLS) - {"propose_write_plan", "create_jira_ticket", "add_jira_comment"} <= tools
    assert "propose_write_plan" in _plan({}).tool_allowlist


@pytest.mark.asyncio
async def test_a_chat_sends_its_core_in_full_and_every_other_offered_tool_by_name():
    offered, context = await _offered_definitions(ACTIVE)
    offered = defer_chat_tools(offered, families=governed_default_tool_set("diagnosis").families, history=[],
                               context=context)
    sent = sent_chat_tool_definitions(offered, context.deferred_tool_catalog, context.discovered_tool_names)
    sent_names = {definition["function"]["name"] for definition in sent}
    assert sent_names <= set(CHAT_CORE_TOOLS) and {"tool_search", "knowledge_search"} <= sent_names
    search = next(definition for definition in sent if definition["function"]["name"] == "tool_search")
    listing = search["function"]["description"]
    families = listing.split("\n", 1)[1]
    # One line per family, at most 1k characters; a search names the tools.
    assert len(families) <= 1000, len(families)
    assert "- connector_writes: Jira" in families and "(confirmed write plan only)" in families
    assert {"create_jira_ticket", "add_jira_comment"} <= sent_names, "the most asked writes need no tool_search"
    assert "propose_write_plan" in sent_names, "weak models get the plan tool in full, never deferred"
    assert "Kubernetes" in families and "AWS" not in families, "the list is already filtered"
    full = len(json.dumps(offered))
    assert len(json.dumps(sent)) < 15_000 < full, (len(json.dumps(sent)), full)


@pytest.mark.asyncio
async def test_tool_search_loads_a_tool_for_the_next_call_and_the_session_remembers_it(chat_context):  # noqa: F811
    from app.tools.registry import execute_tool

    _user, context = chat_context
    offered, _plain = await _offered_definitions(ACTIVE)
    context.project_config = dict(ACTIVE)
    offered = defer_chat_tools(offered, families=governed_default_tool_set("diagnosis").families, history=[],
                               context=context)

    loaded = await execute_tool("tool_search", {"query": "select:update_jira_ticket,no_such_tool"}, context)
    assert loaded["loaded"] == ["update_jira_ticket"]
    assert "schemas" not in loaded, "the schema is sent with the tools; a copy in the result only grows the history"
    sent = {d["function"]["name"] for d in sent_chat_tool_definitions(offered, context.deferred_tool_catalog,
                                                                     context.discovered_tool_names)}
    assert "update_jira_ticket" in sent
    # A model may select a write it already has in full; that is "call it", not "stop".
    core = await execute_tool("tool_search", {"query": "select:create_jira_ticket"}, context)
    assert core["loaded"] == [] and core["note"] == ("Already callable, no search needed: create_jira_ticket. "
                                                     "Call it directly.")
    by_keywords = await execute_tool("tool_search", {"query": "kubernetes pods"}, context)
    assert "list_k8s_pods" in by_keywords["loaded"]
    missing = await execute_tool("tool_search", {"query": "select:delete_everything"}, context)
    assert missing["loaded"] == [] and "not available" in missing["note"]

    # A later turn re-derives the loaded tools from the stored messages (no session-metadata write to lose).
    history = [_Message(("tool_search", {"query": "select:update_jira_ticket"})),
               _Message(("transition_jira_ticket", {}))]
    assert session_loaded_tool_names(history, context.deferred_tool_catalog) == {"update_jira_ticket",
                                                                                 "transition_jira_ticket"}


@pytest.mark.asyncio
async def test_a_guessed_tool_name_loads_the_closest_offered_tools_and_a_repeat_gets_a_short_answer(chat_context):  # noqa: F811
    """Guessed names must not get "not available, stop", or a weak model loops."""
    from app.tools.registry import execute_tool

    _user, context = chat_context
    config = dict(ACTIVE, bitbucket_deployment="cloud", bitbucket_url="https://bitbucket.org",
                  bitbucket_username="u", bitbucket_token="t")
    offered, _plain = await _offered_definitions(config)
    context.project_config = config
    defer_chat_tools(offered, families=governed_default_tool_set("diagnosis").families, history=[], context=context)

    guessed = await execute_tool("tool_search", {"query": "select:get_jira_ticket_transitions"}, context)
    assert "list_jira_transitions" in guessed["loaded"] and len(guessed["loaded"]) <= 3
    assert "get_jira_ticket_transitions" in guessed["note"] and "list_jira_transitions" in guessed["note"]
    assert "list_jira_transitions" in context.discovered_tool_names

    prs = await execute_tool("tool_search", {"query": "select:work_item_context,list_bitbucket_pull_requests"},
                             context)
    assert prs["loaded"] == ["work_item_context", "list_bitbucket_pull_requests"]
    core = await execute_tool("tool_search", {"query": "select:get_jira_ticket"}, context)
    assert core["loaded"] == [] and "Already callable" in core["note"]

    again = await execute_tool("tool_search", {"query": "select:get_jira_ticket_transitions"}, context)
    assert again["loaded"] == [] and "already asked" in again["note"] and "list_jira_transitions" in again["note"]
    assert "schemas" not in again


def test_a_provider_cap_cuts_the_chat_writes_after_the_core_never_first():
    """Appended after the whole set, create_jira_ticket would be the first tool a copilot cap (96) removes."""
    plan = _plan({})
    names = plan.tool_allowlist
    assert names.index("create_jira_ticket") < names.index("call_mcp_server_tool") < names.index("list_k8s_pods")
    catalog = {d["function"]["name"]: d for d in get_all_tools_with_plugins(agent_type="diagnosis")}
    definitions = [catalog[name] for name in names if name in catalog]
    kept = {d["function"]["name"] for d in budget_tool_definitions_for_runtime(
        definitions, runtimes=[{"provider": "copilot"}], capability_type="diagnosis", coding_discipline=None,
        priority_tool_names=names)}
    assert len(definitions) > 96 and {"create_jira_ticket", "add_jira_comment", "knowledge_search"} <= kept


@pytest.mark.asyncio
async def test_a_chat_offers_the_clients_reads_of_the_connectors_the_workspace_activated():
    active = await _offered({
        "k8s_api_url": "https://k8s.example.test", "k8s_token": "t",
        "servicenow_url": "https://sn.example.test", "servicenow_username": "u", "servicenow_password": "p",
    })
    assert CLIENT_READS["k8s"] | CLIENT_READS["servicenow"] | CLIENT_READS["platform"] <= active
    bare = await _offered({})
    assert not (CLIENT_READS["aws"] | CLIENT_READS["servicenow"]) & bare, "visibility hides inactive connectors"
    # The Kubernetes reads are built-in tools like v2's get_k8s_events (the cluster's own RBAC answers them).
    assert CLIENT_READS["platform"] | CLIENT_READS["k8s"] <= bare
