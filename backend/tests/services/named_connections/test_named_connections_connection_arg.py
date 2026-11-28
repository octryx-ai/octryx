"""The generic ``connection`` argument, the planned route and the policy view of it."""

from __future__ import annotations

import pytest

from app.services.classification_tool_policy import CLASSIFICATION_TOOL_POLICY_KEY, classification_tool_decision
from app.services.named_connections.route_planner import plan_route, planned_connection_ids
from app.services.named_connections.routes_model import (
    NAMED_CONNECTIONS_KEY,
    ROUTES_UNAVAILABLE,
    NamedConnectionRoutes,
    ResolvedNamedConnection,
)
from app.services.named_connections.tool_routing import routed_execute
from app.services.policy_engine.shadow import reset_shadow_state
from app.tools.context import ToolContext
from app.tools.definitions import get_all_definitions
from tests.policy_engine_support import use_custom_policies

WIKI = "https://wiki.example.test/wiki"


def _named(ref: str, name: str, keys: set[str], scope: str = "workspace", token: str = "") -> ResolvedNamedConnection:
    config = {"confluence_url": WIKI, "confluence_auth_mode": "bearer_pat", "confluence_token": token or f"t-{ref}"}
    return ResolvedNamedConnection(ref, "confluence", name, scope, frozenset(keys), config)


OWN = _named("id-own", "client-a", {"SALES"})
SHARED = _named("id-global", "client-a", {"INFRA"}, scope="global")
OTHER = _named("id-other", "client-b", {"OPS"})


def _config(*named: ResolvedNamedConnection) -> dict:
    return {
        "confluence_url": WIKI, "confluence_auth_mode": "bearer_pat", "confluence_token": "t-default",
        "confluence_allowed_spaces": [{"space_key": "ENG", "enabled": True}],
        NAMED_CONNECTIONS_KEY: NamedConnectionRoutes(tuple(named)),
    }


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, dict]] = []

    async def __call__(self, params: dict, context: ToolContext):
        self.calls.append((params, context.project_config))
        return {"results": [{"id": "1"}], "total": 1}


def _context(config: dict) -> ToolContext:
    return ToolContext(user_id="u", project_ids=["p"], roles=["admin"], session_id="s", project_config=config)


@pytest.mark.parametrize("wanted, token", [("id-other", "t-id-other"), ("CLIENT-B", "t-id-other"),
                                           ("default", "t-default"), ("id-own", "t-id-own")])
async def test_an_explicit_connection_runs_the_call_on_exactly_it(wanted, token) -> None:
    execute = Recorder()
    await routed_execute("list_confluence_pages", {"connection": wanted, "limit": 5},
                         _context(_config(OWN, SHARED, OTHER)), execute)
    params, config = execute.calls[0]
    assert config["confluence_token"] == token
    assert params == {"limit": 5}, "the argument never reaches the tool"


async def test_a_shared_name_an_unknown_connection_and_a_foreign_key_are_refused() -> None:
    execute = Recorder()
    context = _context(_config(OWN, SHARED, OTHER))
    ambiguous = await routed_execute("list_confluence_pages", {"connection": "client-a"}, context, execute)
    assert ambiguous["code"] == "connection_ambiguous"
    assert [c["id"] for c in ambiguous["candidates"]] == ["id-own", "id-global", "id-other", "default"]
    unknown = await routed_execute("list_confluence_pages", {"connection": "nope"}, context, execute)
    assert unknown["code"] == "connection_unknown" and unknown["candidates"][-1]["id"] == "default"
    for wanted in ("id-other", "default"):
        mismatch = await routed_execute("get_confluence_page", {"connection": wanted, "space_key": "sales", "page_id": "1"},
                                        context, execute)
        assert mismatch["code"] == "connection_scope_mismatch" and mismatch["scopes"] == ["SALES"]
    outside = await routed_execute("get_confluence_page", {"connection": "default", "space_key": "XYZ"}, context, execute)
    assert outside["code"] == "connection_scope_mismatch"
    assert execute.calls == []
    served = await routed_execute("get_confluence_page", {"connection": "id-own", "space_key": "sales"}, context, execute)
    assert served["total"] == 1 and execute.calls[0][1]["confluence_token"] == "t-id-own"


async def test_a_fan_out_search_with_an_explicit_connection_runs_on_it_alone() -> None:
    execute = Recorder()
    out = await routed_execute("search_confluence", {"query": "x", "connection": "id-other"},
                               _context(_config(OWN, OTHER)), execute)
    assert [config["confluence_token"] for _, config in execute.calls] == ["t-id-other"]
    assert "connections" not in out


async def test_without_named_connections_only_default_passes() -> None:
    execute = Recorder()
    plain = {"confluence_url": WIKI, "confluence_token": "t-default"}
    context = _context(plain)
    await routed_execute("list_confluence_pages", {"connection": "default"}, context, execute)
    assert execute.calls[0] == ({}, plain)
    refused = await routed_execute("list_confluence_pages", {"connection": "client-a"}, context, execute)
    assert refused["code"] == "connection_unknown" and len(execute.calls) == 1


def test_the_plan_names_the_connection_ids_a_call_uses() -> None:
    config = _config(OWN, SHARED, OTHER)
    assert planned_connection_ids("get_confluence_page", {"space_key": "INFRA"}, config) == ("id-global",)
    assert planned_connection_ids("get_confluence_page", {"space_key": "ENG"}, config) == ("default",)
    assert planned_connection_ids("search_confluence", {"query": "x"}, config) == (
        "id-own", "id-global", "id-other", "default")
    assert planned_connection_ids("get_confluence_page", {"space_key": "XYZ"}, config) == ()
    assert planned_connection_ids("list_confluence_pages", {}, {"confluence_url": WIKI}) == ("default",)
    assert planned_connection_ids("read_file", {"path": "x"}, config) == ()
    assert plan_route("get_confluence_page", {}, {NAMED_CONNECTIONS_KEY: ROUTES_UNAVAILABLE}).refusal["code"] == (
        "named_connection_routes_unavailable")


def test_a_custom_cedar_policy_sees_the_connection_of_a_call() -> None:
    section = {"level": "internal", "workspace_id": "w", "connectors": {"confluence": "read_write"},
               "log_masking_required": False}
    config = {**_config(OWN, OTHER), CLASSIFICATION_TOOL_POLICY_KEY: section}
    use_custom_policies('@id("client-b-never")\nforbid (principal, action in [Action::"read_connector", '
                        'Action::"write_connector", Action::"call_tool"], resource)\n'
                        'when { context.connections.contains("id-other") };\n', mode="enforce")
    try:
        denied = classification_tool_decision("get_confluence_page", config, {"space_key": "OPS"})
        allowed = classification_tool_decision("get_confluence_page", config, {"space_key": "SALES"})
        explicit = classification_tool_decision("list_confluence_pages", config, {"connection": "client-b"})
        listing = classification_tool_decision("get_confluence_page", config)
    finally:
        reset_shadow_state()  # the enforced denials are this test's own; the plugin resets the runtime
    assert (denied.allowed, denied.reason, denied.policy_ids) == (False, "cedar_policy_denied", ("client-b-never",))
    assert allowed.allowed and listing.allowed
    assert not explicit.allowed


def test_routed_tool_definitions_carry_the_connection_parameter() -> None:
    definitions = get_all_definitions()
    for name in ("get_confluence_page", "search_jira_tickets", "get_servicenow_record"):
        assert "connection" in definitions[name]["function"]["parameters"]["properties"], name
    assert "connection" not in definitions["knowledge_search"]["function"]["parameters"].get("properties", {})
