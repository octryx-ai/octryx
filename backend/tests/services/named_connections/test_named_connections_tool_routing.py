"""Named connections route chat and MCP connector tool calls."""

from __future__ import annotations

import base64
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

import app.tools._confluence_access as confluence_access
from app.services.named_connections import resolver as resolver_module
from app.services.named_connections.contract import NamedConnection
from app.services.named_connections.routes_model import (
    NAMED_CONNECTIONS_KEY,
    NamedConnectionRoutes,
    ResolvedNamedConnection,
)
from app.services.named_connections.store import public_config
from app.services.named_connections.tool_routing import routed_execute, scope_keys
from app.tools.confluence import SearchConfluence
from app.tools.context import ToolContext

WIKI = "https://wiki.example.test/wiki"
FAKE_A, FAKE_B, FAKE_DEFAULT = "fake-pat-a", "fake-pat-b", "fake-default-password"


def _named(name: str, tool: str, keys: set[str], **config) -> ResolvedNamedConnection:
    return ResolvedNamedConnection(f"id-{name}", tool, name, "workspace", frozenset(keys), config)


def _confluence_config(*named: ResolvedNamedConnection, spaces=("ENG",)) -> dict:
    return {
        "confluence_url": WIKI,
        "confluence_auth_mode": "basic",
        "confluence_username": "default-user",
        "confluence_password": FAKE_DEFAULT,
        "confluence_allowed_spaces": [{"space_key": key, "enabled": True} for key in spaces],
        NAMED_CONNECTIONS_KEY: NamedConnectionRoutes(tuple(named)),
    }


A = _named("client-a", "confluence", {"SALES"}, confluence_url=WIKI, confluence_auth_mode="bearer_pat",
           confluence_token=FAKE_A)
B = _named("client-b", "confluence", {"INFRA"}, confluence_url=WIKI, confluence_auth_mode="bearer_pat",
           confluence_token=FAKE_B)


def _context(config: dict) -> ToolContext:
    return ToolContext(user_id="u", project_ids=["p"], roles=["admin"], session_id="s", project_config=config)


class Recorder:
    def __init__(self, result=None) -> None:
        self.configs: list[dict] = []
        self.contexts: list[ToolContext] = []
        self.result = result

    async def __call__(self, params: dict, context: ToolContext):
        self.contexts.append(context)
        self.configs.append(context.project_config)
        if callable(self.result):
            return self.result(context.project_config)
        return self.result if self.result is not None else {"ok": True}


def test_scope_keys_come_from_the_declared_parameters_only() -> None:
    assert scope_keys("confluence", "get_confluence_page", {"space_key": "sales", "page_id": "1"}) == ("SALES",)
    assert scope_keys("jira", "get_jira_ticket", {"ticket_id": "ops-12"}) == ("OPS",)
    assert scope_keys("jira", "add_issues_to_sprint", {"ticket_ids": ["OPS-1", "RIVER-2", "OPS-3"]}) == ("OPS", "RIVER")
    assert scope_keys("jira", "list_jira_priorities", {}) == ()
    assert scope_keys("servicenow", "list_servicenow_incidents", {}) == ("incident",)
    assert scope_keys("servicenow", "get_servicenow_record", {"table": "Change_Request"}) == ("change_request",)


async def test_a_scoped_call_runs_with_exactly_its_connection() -> None:
    execute = Recorder()
    await routed_execute("get_confluence_page", {"space_key": "sales", "page_id": "1"},
                         _context(_confluence_config(A, B)), execute)
    config = execute.configs[0]
    assert config["confluence_token"] == FAKE_A and "confluence_password" not in config
    assert config["confluence_allowed_spaces"] == ["SALES"] and NAMED_CONNECTIONS_KEY not in config


async def test_an_unbound_scope_runs_on_the_default_only_when_its_allowlist_allows_it() -> None:
    execute = Recorder()
    await routed_execute("list_confluence_pages", {"space_key": "ENG"}, _context(_confluence_config(A)), execute)
    assert execute.configs[0]["confluence_password"] == FAKE_DEFAULT

    refused = await routed_execute("list_confluence_pages", {"space_key": "OTHER"},
                                   _context(_confluence_config(A)), execute)
    assert refused["code"] == "connection_not_configured_for_scope" and len(execute.configs) == 1


async def test_scopes_of_two_connections_in_one_call_are_refused() -> None:
    jira_a = _named("ops", "jira", {"OPS"}, jira_url="https://jira.example.test", jira_token=FAKE_A)
    config = {"jira_url": "https://jira.example.test", "jira_token": FAKE_DEFAULT,
              NAMED_CONNECTIONS_KEY: NamedConnectionRoutes((jira_a,))}
    execute = Recorder()
    refused = await routed_execute("add_issues_to_sprint", {"ticket_ids": ["OPS-1", "RIVER-2"]},
                                   _context(config), execute)
    assert refused["code"] == "scope_spans_connections" and refused["connections"] == ["default", "ops"]
    assert execute.configs == []


async def test_an_unscoped_call_runs_on_the_default_without_any_bound_key() -> None:
    execute = Recorder()
    await routed_execute("add_confluence_comment", {"page_id": "1"},
                         _context(_confluence_config(A, spaces=("ENG", "SALES"))), execute)
    assert execute.configs[0]["confluence_allowed_spaces"] == [{"space_key": "ENG", "enabled": True}]


async def test_without_named_connections_the_call_passes_through_unchanged() -> None:
    execute = Recorder()
    context = _context({"confluence_url": WIKI})
    await routed_execute("search_confluence", {"query": "x"}, context, execute)
    assert execute.contexts == [context]
    other = Recorder()
    routed = _context(_confluence_config(A))
    await routed_execute("list_kubernetes_pods", {"space_key": "SALES"}, routed, other)
    assert other.contexts == [routed]


async def test_an_unrestricted_jira_default_never_reports_a_bound_project() -> None:
    ops = _named("ops", "jira", {"OPS"}, jira_url="https://jira.example.test", jira_token=FAKE_A)
    config = {"jira_url": "https://jira.example.test", "jira_token": FAKE_DEFAULT,
              NAMED_CONNECTIONS_KEY: NamedConnectionRoutes((ops,))}

    def result(cfg: dict) -> dict:
        if cfg["jira_token"] == FAKE_A:
            return {"results": [{"key": "OPS-1"}], "total": 1}
        return {"results": [{"key": "OPS-2"}, {"key": "RIVER-3"}], "total": 2}

    merged = await routed_execute("search_jira_tickets", {"query": "x"}, _context(config), Recorder(result))
    assert [item["key"] for item in merged["results"]] == ["OPS-1", "RIVER-3"]
    assert merged["connections"] == [
        {"connection": "ops", "connection_id": "id-ops", "count": 1},
        {"connection": "default", "connection_id": "default", "count": 1},
    ]


async def test_a_failing_connection_is_named_and_the_others_still_answer() -> None:
    def result(cfg: dict) -> dict:
        return {"error": "Confluence returned 401"} if cfg.get("confluence_token") == FAKE_B else {"results": [1]}

    merged = await routed_execute("search_confluence", {"query": "x"}, _context(_confluence_config(A, B)),
                                  Recorder(result))
    assert merged["results"] == [1, 1]
    assert {"connection": "client-b", "connection_id": "id-client-b", "error": "Confluence returned 401"} in merged["connections"]


@pytest.fixture
def fake_confluence(monkeypatch) -> list[tuple[str, str]]:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cql = parse_qs(urlsplit(str(request.url)).query)["cql"][0]
        seen.append((cql, request.headers.get("Authorization", "")))
        results = [
            {"id": str(index), "title": f"{space} page", "space": {"key": space}, "version": {"number": 1},
             "_links": {"webui": f"/spaces/{space}/pages/{index}"}}
            for index, space in enumerate(("SALES", "INFRA", "ENG"), start=1) if f'"{space}"' in cql
        ]
        return httpx.Response(200, json={"results": results})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(confluence_access, "egress_transport", lambda *_args, **_kwargs: transport)
    return seen


async def test_a_search_without_a_space_runs_once_per_connection_on_its_own_spaces(fake_confluence) -> None:
    merged = await routed_execute("search_confluence", {"query": "runbook"},
                                  _context(_confluence_config(A, B)), SearchConfluence().execute)

    assert sorted(item["space_key"] for item in merged["results"]) == ["ENG", "INFRA", "SALES"]
    assert merged["connections"] == [
        {"connection": "client-a", "connection_id": "id-client-a", "count": 1},
        {"connection": "client-b", "connection_id": "id-client-b", "count": 1},
        {"connection": "default", "connection_id": "default", "count": 1},
    ]
    basic = "Basic " + base64.b64encode(f"default-user:{FAKE_DEFAULT}".encode()).decode()
    by_auth = {auth: cql for cql, auth in fake_confluence}
    assert 'space in ("SALES")' in by_auth[f"Bearer {FAKE_A}"]
    assert 'space in ("INFRA")' in by_auth[f"Bearer {FAKE_B}"]
    assert 'space in ("ENG")' in by_auth[basic] and '"SALES"' not in by_auth[basic]
    assert len(fake_confluence) == 3


async def test_the_mcp_connector_tool_routes_like_the_chat(monkeypatch, fake_confluence) -> None:
    from app.services import mcp_connector_tools as module

    config = _confluence_config(A, B)

    async def authorized(params, context):
        return type("Authorized", (), {"project_id": "p"})()

    async def project_config(db, *, user_id, workspace_id):
        return config

    monkeypatch.setattr(module, "authorized_workspace", authorized)
    monkeypatch.setattr(module, "chat_tool_project_config", project_config)
    tool = module.CONNECTOR_MCP_TOOLS["search_confluence"]

    result = await tool.execute({"query": "x", "space_key": "INFRA"}, replace(_context({}), db=None))

    assert [item["space_key"] for item in result["results"]] == ["INFRA"]
    assert fake_confluence[0][1] == f"Bearer {FAKE_B}"


@pytest.mark.parametrize("untyped", [{"forged": True}, "NamedConnectionRoutes(...)", [], {}])
async def test_untyped_routes_fail_closed_instead_of_using_the_default(untyped) -> None:
    execute = Recorder()
    config = {"jira_url": "https://jira.example.test", "jira_token": FAKE_DEFAULT, NAMED_CONNECTIONS_KEY: untyped}
    refused = await routed_execute("get_jira_ticket", {"ticket_id": "OPS-1"}, _context(config), execute)
    assert refused["code"] == "named_connection_routes_unavailable" and refused["connector"] == "jira"
    assert execute.configs == []
    other = Recorder()
    await routed_execute("list_kubernetes_pods", {}, _context(config), other)
    assert len(other.configs) == 1


def _lazy(name: str, keys: set[str], token_ref: str) -> ResolvedNamedConnection:
    config = {"confluence_url": WIKI, "confluence_auth_mode": "bearer_pat"}
    source = NamedConnection(f"id-{name}", "confluence", "p", name,
                             {**config, "confluence_token_secret_ref": token_ref}, frozenset(keys))
    return ResolvedNamedConnection(f"id-{name}", "confluence", name, "workspace", frozenset(keys), config, source)


async def test_only_the_secret_of_the_serving_connection_is_resolved(monkeypatch) -> None:
    resolved: list[str] = []

    async def fake_resolved_config(db, connection):
        resolved.append(connection.name)
        return {**public_config(connection), "confluence_token": f"secret-of-{connection.name}"}

    monkeypatch.setattr(resolver_module, "resolved_config", fake_resolved_config)
    config = _confluence_config(_lazy("client-a", {"SALES"}, "ref-a"), _lazy("client-b", {"INFRA"}, "ref-b"))
    execute = Recorder()
    context = replace(_context(config), db=object())

    await routed_execute("get_confluence_page", {"space_key": "SALES", "page_id": "1"}, context, execute)

    assert resolved == ["client-a"]
    assert execute.configs[0]["confluence_token"] == "secret-of-client-a"
    resolved.clear()
    await routed_execute("list_confluence_pages", {"space_key": "ENG"}, context, Recorder())
    assert resolved == []


async def test_a_named_connection_contributes_only_its_connection_unit() -> None:
    stray = _named("client-a", "confluence", {"SALES"}, confluence_url=WIKI, confluence_auth_mode="bearer_pat",
                   confluence_token=FAKE_A, confluence_max_results=999, approval_policy={"mode": "none"},
                   confluence_allowed_spaces=["ENG", "SALES", "HR"])
    base = {**_confluence_config(stray), "confluence_max_results": 25}
    execute = Recorder()
    await routed_execute("get_confluence_page", {"space_key": "SALES", "page_id": "1"}, _context(base), execute)
    config = execute.configs[0]
    assert config["confluence_token"] == FAKE_A and config["confluence_max_results"] == 25
    assert "approval_policy" not in config and config["confluence_allowed_spaces"] == ["SALES"]
