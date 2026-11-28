"""The runtime reads connections available in the Workspace through ``effective()``."""

from __future__ import annotations

import uuid

import pytest

from app.models import BuiltInToolConfig, ConnectionDeviation, ConnectionWorkspace, ConnectorNamedConnection, Project
from app.services.named_connections.connection_gate import hidden_reason
from app.services.named_connections.contract import named_secret_field
from app.services.named_connections.route_planner import plan_connector, plan_route
from app.services.named_connections.service_config import ConnectionRefusalError, service_connection_config
from app.services.named_connections.workspace_routes import workspace_routes
from app.services.secret import set_secret_value
from app.services.tool_config import merge_tool_configs_into_project_config
from app.tools.visibility import tool_visibility_decision

ENTRY = {"jira_url": "https://jira.default.example.test", "jira_auth_mode": "bearer_pat", "jira_token": "fake-default"}
READ_TOOL, WRITE_TOOL = "get_jira_ticket", "add_jira_comment"


async def _workspace(db, config: dict | None = None) -> str:
    project = Project(name=f"conn-{uuid.uuid4().hex[:8]}")
    db.add(project)
    await db.flush()
    db.add(BuiltInToolConfig(tool_name="jira", project_id=project.id, config=dict(ENTRY if config is None else config),
                             is_active=True))
    await db.flush()
    return project.id


async def _connection(db, name: str, keys: list[str], *, project_id: str | None = None, workspaces=(),
                      available_in: str = "selected", level: str = "write", active: bool = True) -> str:
    row = ConnectorNamedConnection(
        id=str(uuid.uuid4()), tool_name="jira", project_id=project_id, scope_key=project_id or "global", name=name,
        bound_scopes=keys, config={"jira_url": f"https://{name}.example.test", "jira_auth_mode": "bearer_pat"},
        available_in=available_in, agent_tools_level=level, is_active=active,
    )
    db.add(row)
    await db.flush()
    for workspace_id in workspaces:
        db.add(ConnectionWorkspace(connection_id=row.id, workspace_id=workspace_id))
    stored = await set_secret_value(db, tool_name="jira", field_name=named_secret_field("jira_token", row.id),
                                    project_id=project_id, value=f"fake-{name}")
    row.config = {**row.config, "jira_token_secret_ref": stored.id}
    await db.flush()
    return row.id


async def _merged(db, workspace_id: str) -> dict:
    return await merge_tool_configs_into_project_config(db, workspace_id, {})


def _ticket(key: str = "OPS") -> dict:
    return {"ticket_id": f"{key}-1", "comment": "x"}


async def test_a_connection_serves_only_the_workspaces_it_is_available_in(db) -> None:
    ws_a, ws_b = await _workspace(db), await _workspace(db)
    selected = await _connection(db, "ops-a", ["OPS"], workspaces=[ws_a])
    owned = ConnectorNamedConnection(id=str(uuid.uuid4()), tool_name="jira", project_id=None, scope_key="global",
                                     name="owned-b", bound_scopes=["RIVER"], config={}, available_in="selected",
                                     owner_kind="workspace", owner_workspace_id=ws_b, agent_tools_level="write")
    db.add(owned)
    await db.flush()

    in_a = await workspace_routes(db, ws_a, ["jira"], secrets=False)
    in_b = await workspace_routes(db, ws_b, ["jira"], secrets=False)
    assert [(c.id, c.scope) for c in in_a.connections] == [(selected, "global")]
    assert [(c.id, c.scope) for c in in_b.connections] == [(owned.id, "workspace")], "an owned one is own"
    plan = plan_route(READ_TOOL, _ticket(), await _merged(db, ws_a))
    assert plan.connection_ids == (selected,)
    plan_b = plan_route(READ_TOOL, _ticket(), await _merged(db, ws_b))
    assert plan_b.connection_ids == ("default",), "not available in B: the default serves OPS there"


async def test_existing_named_connections_route_exactly_as_before(db) -> None:
    ws_a = await _workspace(db)
    own = await _connection(db, "ws-ops", ["OPS"], project_id=ws_a)
    shared = await _connection(db, "global-ops", ["OPS", "RIVER"], project_id=None, available_in="all")
    merged = await _merged(db, ws_a)
    assert plan_route(WRITE_TOOL, _ticket("OPS"), merged).connection_ids == (own,), "the Workspace binding wins"
    assert plan_route(WRITE_TOOL, _ticket("RIVER"), merged).connection_ids == (shared,)
    assert plan_route(WRITE_TOOL, _ticket("ENG"), merged).connection_ids == ("default",)
    assert tool_visibility_decision(WRITE_TOOL, merged).visible


async def test_a_disabled_connection_refuses_every_use_and_never_falls_back(db) -> None:
    ws_a = await _workspace(db)
    disabled = await _connection(db, "ops-off", ["OPS"], workspaces=[ws_a], active=False)
    merged = await _merged(db, ws_a)
    plan = plan_route(READ_TOOL, _ticket(), merged)
    assert plan.refusal["code"] == "connection_disabled" and plan.refusal["state"] == "needs_configuration"
    assert plan.refusal["connection_id"] == disabled
    assert plan_connector("jira", merged, keys=("OPS",)).refusal["code"] == "connection_disabled"
    with pytest.raises(ConnectionRefusalError) as refused:
        await service_connection_config(db, ws_a, "jira", keys=["OPS"], base=merged)
    assert refused.value.code == "connection_disabled"
    assert "fake-default" not in str(plan.refusal)


@pytest.mark.parametrize(("level", "read_ok", "write_ok"), [
    ("off", False, False), ("read", True, False), ("write", True, True),
])
async def test_the_agent_tools_level_gates_visibility_and_calls(db, level, read_ok, write_ok) -> None:
    # The Workspace entry is an access switch without its own account: the connection is the only one serving.
    ws_a = await _workspace(db, {"jira_allowed_projects": ["OPS"]})
    connection = await _connection(db, "ops", ["OPS"], workspaces=[ws_a], level=level)
    merged = await _merged(db, ws_a)
    for tool, allowed in ((READ_TOOL, read_ok), (WRITE_TOOL, write_ok)):
        plan = plan_route(tool, _ticket(), merged)
        assert (plan.refusal is None) is allowed, (tool, plan.refusal)
        assert (hidden_reason(tool, merged) is None) is allowed
        if not allowed:
            assert plan.refusal["state"] == "needs_configuration" and plan.refusal["connection_id"] == connection
            assert plan.refusal["code"] in ("connection_agent_tools_off", "connection_agent_tools_read_only")
            assert not tool_visibility_decision(tool, merged).visible
    assert plan_connector("jira", merged, keys=("OPS",)).refusal is None, "a platform service is no agent tool"


async def test_a_workspace_deviation_narrows_the_level_in_that_workspace_only(db) -> None:
    ws_a, ws_b = await _workspace(db), await _workspace(db)
    connection = await _connection(db, "ops", ["OPS"], workspaces=[ws_a, ws_b], level="write")
    db.add(ConnectionDeviation(connection_id=connection, workspace_id=ws_a, fields={"agent_tools": {"level": "read"}}))
    await db.flush()
    in_a = plan_route(WRITE_TOOL, _ticket(), await _merged(db, ws_a))
    assert in_a.refusal["code"] == "connection_agent_tools_read_only"
    assert plan_route(READ_TOOL, _ticket(), await _merged(db, ws_a)).connection_ids == (connection,)
    assert plan_route(WRITE_TOOL, _ticket(), await _merged(db, ws_b)).connection_ids == (connection,)


async def test_two_connections_of_the_same_precedence_on_one_key_are_refused_not_chosen(db) -> None:
    ws_a = await _workspace(db)
    await _connection(db, "ops-1", ["OPS"], workspaces=[ws_a])
    await _connection(db, "ops-2", ["OPS", "RIVER"], workspaces=[ws_a])
    merged = await _merged(db, ws_a)
    plan = plan_route(READ_TOOL, _ticket("OPS"), merged)
    assert plan.refusal["code"] == "connection_ambiguous" and plan.refusal["state"] == "needs_configuration"
    assert plan.refusal["scopes"] == ["OPS"]
    assert plan_route(READ_TOOL, _ticket("RIVER"), merged).refusal is None, "an unambiguous key still routes"
    with pytest.raises(ConnectionRefusalError) as refused:
        await service_connection_config(db, ws_a, "jira", keys=["OPS"], base=merged)
    assert refused.value.code == "connection_ambiguous"
    # An own connection on the key settles it: the Workspace binding wins over both shared ones.
    own = await _connection(db, "ws-ops", ["OPS"], project_id=ws_a)
    assert plan_route(READ_TOOL, _ticket("OPS"), await _merged(db, ws_a)).connection_ids == (own,)


@pytest.mark.parametrize("level", ["off", "read"])
async def test_the_platforms_own_config_lookup_is_not_limited_by_the_agent_tools_level(db, level) -> None:
    from app.services.named_connections.service_config import planned_tool_config

    ws_a = await _workspace(db, {"jira_allowed_projects": ["OPS"]})
    await _connection(db, "ops", ["OPS"], workspaces=[ws_a], level=level)
    merged = await _merged(db, ws_a)
    assert planned_tool_config(WRITE_TOOL, _ticket(), merged) == {}
    assert planned_tool_config(WRITE_TOOL, _ticket(), merged, agent_tool=False)["jira_url"] == "https://ops.example.test"


async def test_the_client_lists_the_same_connector_tools_as_the_chat(db, monkeypatch) -> None:
    from contextlib import asynccontextmanager

    from app.services import mcp_knowledge_protocol
    from app.services.mcp_extra_tools import EXTRA_GOVERNED_MCP_TOOLS
    from app.services.mcp_governed_knowledge import GOVERNED_MCP_TOOLS

    for name, entry in EXTRA_GOVERNED_MCP_TOOLS.items():
        monkeypatch.setitem(GOVERNED_MCP_TOOLS, name, entry)
    ws_a = await _workspace(db, {"jira_allowed_projects": ["OPS"]})
    await _connection(db, "ops", ["OPS"], workspaces=[ws_a], level="off")
    await db.commit()

    async def connection_workspace(server, session):
        return ws_a

    @asynccontextmanager
    async def test_session():
        yield db

    monkeypatch.setattr(mcp_knowledge_protocol, "_connection_workspace", connection_workspace)
    monkeypatch.setattr(mcp_knowledge_protocol, "async_session_factory", test_session)
    names = {tool.name for tool in await mcp_knowledge_protocol.build_knowledge_mcp_server().list_tools()}
    assert not tool_visibility_decision(READ_TOOL, await _merged(db, ws_a)).visible
    assert READ_TOOL not in names and "search_jira_tickets" not in names
    # knowledge_search is a registry tool: tool_search finds it (test_session_mcp_surface), tools/list leaves it out.
    assert "tool_search" in names and "knowledge_search" not in names
