"""Named connections: the contract, the one resolver and the per-connection secret binding."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import event

from app.models import BuiltInToolConfig, ConnectorNamedConnection, Project
from app.services.named_connections.contract import (
    CODE_NAME_INVALID,
    CODE_NAME_RESERVED,
    CODE_SCOPES_INVALID,
    NamedConnection,
    NamedConnectionError,
    bound_elsewhere,
    named_secret_field,
    validate_bound_scopes,
    validate_name,
)
from app.services.named_connections.resolver import connection_config, default_allows
from app.services.named_connections.routes_model import (
    NAMED_CONNECTIONS_KEY,
    NamedConnectionRoutes,
    ResolvedNamedConnection,
    routes_of,
)
from app.services.named_connections.workspace_routes import workspace_routes
from app.services.secret import set_secret_value
from app.services.tool_config import merge_tool_configs_into_project_config

FAKE_A = "fake-secret-a"
FAKE_B = "fake-secret-b"


def _conn(name: str, tool: str, keys: set[str], scope: str = "workspace", **config) -> ResolvedNamedConnection:
    return ResolvedNamedConnection(
        id=f"id-{name}", tool_name=tool, name=name, scope=scope, bound_scopes=frozenset(keys), config=config
    )


@pytest.mark.parametrize("name", ["", "-x", "a" * 65, "with space", "x/y", None, 3])
def test_invalid_names_are_refused(name) -> None:
    with pytest.raises(NamedConnectionError) as refused:
        validate_name(name)
    assert refused.value.code == CODE_NAME_INVALID


@pytest.mark.parametrize("name", ["default", "Default", " DEFAULT "])
def test_default_is_reserved(name) -> None:
    with pytest.raises(NamedConnectionError) as refused:
        validate_name(name)
    assert refused.value.code == CODE_NAME_RESERVED


def test_names_and_scopes_are_canonical() -> None:
    assert validate_name(" sales-client_A.1 ") == "sales-client_A.1"
    assert validate_bound_scopes("confluence", ["sales", "SALES", "infra", "~jdoe"]) == ("SALES", "INFRA", "~JDOE")
    assert validate_bound_scopes("jira", "ops, River") == ("OPS", "RIVER")
    assert validate_bound_scopes("servicenow", ["Incident"]) == ("incident",)


@pytest.mark.parametrize("raw", [[], None, "", ["bad key"], ["a-b"], [3], ["x"] * 101])
def test_invalid_scopes_are_refused(raw) -> None:
    keys = ["K" + str(index) for index in range(101)] if raw == ["x"] * 101 else raw
    with pytest.raises(NamedConnectionError) as refused:
        validate_bound_scopes("confluence", keys)
    assert refused.value.code == CODE_SCOPES_INVALID


def test_a_key_bound_by_another_connection_is_reported_with_its_name() -> None:
    other = NamedConnection("1", "confluence", "p", "client-a", {}, frozenset({"SALES"}))
    assert bound_elsewhere("confluence", ("sales", "INFRA"), [other]) == [("sales", "client-a")]
    assert bound_elsewhere("confluence", ("INFRA",), [other]) == []


def test_exact_binding_wins_and_the_workspace_binding_overrides_a_global_one() -> None:
    workspace = _conn("ws-sales", "confluence", {"SALES"})
    global_rt = _conn("global-sales", "confluence", {"SALES", "OPS"}, scope="global")
    routes = NamedConnectionRoutes((workspace, global_rt))
    assert routes.match("confluence", "sales") is workspace
    assert routes.match("confluence", "OPS") is global_rt
    assert routes.match("confluence", "ENG") is None
    assert routes.match("jira", "SALES") is None
    assert routes.bound_keys("confluence") == {"SALES", "OPS"}


BASE = {
    "confluence_url": "https://default.example.test/wiki",
    "confluence_auth_mode": "basic",
    "confluence_username": "default-user",
    "confluence_password": "fake-default",
    "confluence_allowed_spaces": [
        {"space_key": "SALES", "enabled": True, "allowed_pages": ["1"]},
        {"space_key": "ENG", "enabled": True},
    ],
    "confluence_allowed_pages": [{"id": "7"}],
}


def test_a_named_connection_replaces_the_whole_unit_and_reads_only_its_bound_scopes() -> None:
    named = _conn(
        "sales", "confluence", {"SALES", "INFRA"}, confluence_url="https://sales.example.test/wiki",
        confluence_auth_mode="bearer_pat", confluence_token=FAKE_A,
    )
    config = connection_config(BASE, "confluence", NamedConnectionRoutes((named,)), named)
    assert config["confluence_url"] == "https://sales.example.test/wiki"
    assert config["confluence_token"] == FAKE_A
    assert "confluence_username" not in config and "confluence_password" not in config
    assert config["confluence_allowed_spaces"] == ["INFRA", {"space_key": "SALES", "enabled": True, "allowed_pages": ["1"]}]
    assert config["confluence_allowed_pages"] == [{"id": "7"}]
    assert NAMED_CONNECTIONS_KEY not in config


def test_the_default_connection_loses_every_bound_key() -> None:
    routes = NamedConnectionRoutes((_conn("sales", "confluence", {"SALES"}),))
    config = connection_config({**BASE, NAMED_CONNECTIONS_KEY: routes}, "confluence", routes, None)
    assert config["confluence_allowed_spaces"] == [{"space_key": "ENG", "enabled": True}]
    assert config["confluence_password"] == "fake-default"
    assert default_allows("confluence", config, "eng") and not default_allows("confluence", config, "SALES")
    assert NAMED_CONNECTIONS_KEY not in config


def test_a_default_whose_keys_are_all_bound_serves_nothing_instead_of_everything() -> None:
    base = {"jira_url": "https://jira.example.test", "jira_auth_mode": "bearer_pat", "jira_token": "fake-default",
            "jira_allowed_projects": ["OPS"]}
    routes = NamedConnectionRoutes((_conn("ops", "jira", {"OPS"}),))
    config = connection_config(base, "jira", routes, None)
    assert "jira_url" not in config and "jira_token" not in config and "jira_auth_mode" not in config
    assert config["jira_allowed_projects"] == []


def test_without_bindings_the_default_is_unchanged_and_jira_unlisted_means_any() -> None:
    base = {"jira_url": "https://jira.example.test", "jira_allowed_projects": None}
    assert connection_config(base, "jira", NamedConnectionRoutes(), None) == base
    assert default_allows("jira", base, "ANY")
    assert not default_allows("confluence", {"confluence_space_key": "ENG"}, "OPS")
    assert default_allows("confluence", {"confluence_space_key": "ENG"}, "eng")
    disabled = {"confluence_allowed_spaces": [{"space_key": "ENG", "enabled": False}]}
    assert not default_allows("confluence", disabled, "ENG")


def test_a_plain_value_never_counts_as_routes_and_routes_never_print_a_secret() -> None:
    assert routes_of({NAMED_CONNECTIONS_KEY: {"connections": []}}).connections == ()
    assert routes_of({NAMED_CONNECTIONS_KEY: {"connections": []}}).unavailable
    assert not routes_of({}).unavailable and not routes_of(None).unavailable
    routes = NamedConnectionRoutes((_conn("sales", "confluence", {"SALES"}, confluence_token=FAKE_A),))
    assert FAKE_A not in repr(routes) and FAKE_A not in json.dumps({"x": routes}, default=str)


async def _workspace(db, *, active: bool = True) -> str:
    project = Project(name=f"named-{uuid.uuid4().hex[:8]}")
    db.add(project)
    await db.flush()
    db.add(BuiltInToolConfig(tool_name="confluence", project_id=project.id, config=dict(BASE), is_active=active))
    await db.flush()
    return project.id


async def _named(db, project_id, name: str, keys: list[str], secret: str, *, secret_for: str | None = None) -> str:
    row = ConnectorNamedConnection(
        id=str(uuid.uuid4()), tool_name="confluence", project_id=project_id, scope_key=project_id or "global",
        name=name, bound_scopes=keys,
        config={"confluence_url": f"https://{name}.example.test/wiki", "confluence_auth_mode": "bearer_pat"},
    )
    db.add(row)
    await db.flush()
    stored = await set_secret_value(
        db, tool_name="confluence", field_name=named_secret_field("confluence_token", secret_for or row.id),
        project_id=project_id, value=secret,
    )
    row.config = {**row.config, "confluence_token_secret_ref": stored.id}
    await db.flush()
    return row.id


async def test_routes_resolve_each_secret_for_its_own_connection_only(db) -> None:
    project_id = await _workspace(db)
    await _named(db, project_id, "client-a", ["SALES"], FAKE_A)
    await _named(db, project_id, "client-b", ["INFRA"], FAKE_B, secret_for=str(uuid.uuid4()))
    await _named(db, None, "global-ops", ["OPS"], "fake-global")

    routes = await workspace_routes(db, project_id)

    by_name = {connection.name: connection for connection in routes.connections}
    assert [c.name for c in routes.connections] == ["client-a", "client-b", "global-ops"]
    assert by_name["client-a"].config["confluence_token"] == FAKE_A
    assert "confluence_token" not in by_name["client-b"].config
    assert by_name["global-ops"].scope == "global" and by_name["global-ops"].config["confluence_token"] == "fake-global"
    assert all(not key.endswith("_secret_ref") for c in routes.connections for key in c.config)


async def test_routes_of_every_connector_cost_one_query_per_kind(db) -> None:
    project_id = await _workspace(db)
    db.add(BuiltInToolConfig(tool_name="jira", project_id=project_id, config={}, is_active=True))
    db.add(BuiltInToolConfig(tool_name="servicenow", project_id=project_id, config={}, is_active=False))
    await _named(db, project_id, "client-a", ["SALES"], FAKE_A)
    await _named(db, None, "global-ops", ["OPS"], "fake-global")
    db.add(ConnectorNamedConnection(
        id=str(uuid.uuid4()), tool_name="servicenow", project_id=project_id, scope_key=project_id,
        name="inactive", bound_scopes=["incident"], config={}))
    await db.flush()
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append(statement)

    sync_connection = (await db.connection()).sync_connection
    event.listen(sync_connection, "before_cursor_execute", record)
    try:
        routes = await workspace_routes(db, project_id, secrets=False)
    finally:
        event.remove(sync_connection, "before_cursor_execute", record)

    assert len(statements) == 4, statements
    assert [(c.tool_name, c.name, c.scope) for c in routes.connections] == [
        ("confluence", "client-a", "workspace"), ("confluence", "global-ops", "global")]


async def test_named_connections_apply_only_while_the_workspace_entry_is_active(db) -> None:
    project_id = await _workspace(db, active=False)
    await _named(db, project_id, "client-a", ["SALES"], FAKE_A)
    assert (await workspace_routes(db, project_id)).connections == ()
    assert (await workspace_routes(db, None)).connections == ()


async def test_the_merged_project_config_carries_typed_routes_and_ignores_injected_ones(db) -> None:
    project_id = await _workspace(db)
    merged_without = await merge_tool_configs_into_project_config(db, project_id, {NAMED_CONNECTIONS_KEY: ["x"]})
    assert NAMED_CONNECTIONS_KEY not in merged_without

    await _named(db, project_id, "client-a", ["SALES"], FAKE_A)
    merged = await merge_tool_configs_into_project_config(db, project_id, {NAMED_CONNECTIONS_KEY: ["x"]})
    assert type(merged[NAMED_CONNECTIONS_KEY]) is NamedConnectionRoutes
    assert routes_of(merged).match("confluence", "SALES").name == "client-a"



async def test_the_merged_config_holds_no_secret_and_a_call_resolves_only_its_connection(db) -> None:
    from app.services.named_connections.tool_routing import routed_execute
    from app.tools.context import ToolContext

    project_id = await _workspace(db)
    await _named(db, project_id, "client-a", ["SALES"], FAKE_A)
    await _named(db, project_id, "client-b", ["INFRA"], FAKE_B)
    merged = await merge_tool_configs_into_project_config(db, project_id, {})
    routes = routes_of(merged)
    assert all("confluence_token" not in connection.config for connection in routes.connections)

    seen: list[dict] = []

    async def execute(params, context):
        seen.append(context.project_config)
        return {"ok": True}

    context = ToolContext(user_id="u", project_ids=[project_id], roles=["admin"], session_id="s",
                          project_config=merged, db=db)
    await routed_execute("get_confluence_page", {"space_key": "INFRA", "page_id": "1"}, context, execute)
    assert seen[0]["confluence_token"] == FAKE_B and FAKE_A not in json.dumps(seen[0], default=str)
