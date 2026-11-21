"""Uses that name their connection, the default connection and the runtime state.

- an intake (``work_item_sync_configs.connection_id``) and a Knowledge source (``knowledge_source_connectors
  .connection_id``) read through the connection they name, with its grant and the Workspace's deviation of the use
  (off → ``connection_use_disabled``; a key outside the deviation's scope → ``scope_not_allowed``); disabled →
  ``connection_disabled``; not available in the Workspace → ``connection_not_available``;
- a use that names no connection reads through the default path (the default connection, the resolver);
- the one available connection that binds no key is the Workspace's default: its own credential is read, not the
  entry's; disabled, it is no longer the default;
- an unauthenticated runtime use marks the connection ``failing`` with one sentence.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import (
    BuiltInToolConfig,
    ConnectionDeviation,
    ConnectionWorkspace,
    ConnectorNamedConnection,
    Project,
    User,
    WorkItemSyncConfig,
)
from app.services.knowledge.sources.sync.contract import ConnectorError
from app.services.knowledge.sources.sync.scope_connections import resolve_scope_connections
from app.services.named_connections.contract import named_secret_field
from app.services.named_connections.runtime_state import USE_SENTENCES
from app.services.named_connections.tool_routing import routed_execute
from app.services.secret import set_secret_value
from app.services.secure_work.intake.connections import intake_connection_config
from app.services.tool_config import merge_tool_configs_into_project_config
from app.tools.context import ToolContext

URL = "https://jira.example.test"


async def _workspace(db, config: dict | None = None) -> str:
    project = Project(name=f"uses-{uuid.uuid4().hex[:8]}")
    db.add(project)
    await db.flush()
    db.add(BuiltInToolConfig(tool_name="jira", project_id=project.id, is_active=True,
                             config=config if config is not None else {"jira_allowed_projects": ["OPS", "RIVER"]}))
    await db.flush()
    return project.id


async def _connection(db, keys: list[str], workspaces: list[str], *, active: bool = True, level: str = "read") -> str:
    row = ConnectorNamedConnection(
        id=str(uuid.uuid4()), tool_name="jira", project_id=None, scope_key="global", name=f"c-{uuid.uuid4().hex[:6]}",
        bound_scopes=keys, config={"jira_url": URL, "jira_auth_mode": "bearer_pat"}, available_in="selected",
        is_active=active, agent_tools_level=level,
    )
    db.add(row)
    await db.flush()
    for workspace_id in workspaces:
        db.add(ConnectionWorkspace(connection_id=row.id, workspace_id=workspace_id))
    stored = await set_secret_value(db, tool_name="jira", field_name=named_secret_field("jira_token", row.id),
                                    project_id=None, value="fake-connection-token")
    row.config = {**row.config, "jira_token_secret_ref": stored.id}
    await db.flush()
    return row.id


async def _intake(db, workspace_id: str, connection_id: str | None, keys: list[str]) -> WorkItemSyncConfig:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    row = WorkItemSyncConfig(name=f"intake-{uuid.uuid4().hex[:4]}", project_id=workspace_id, source_type="jira",
                             connection_id=connection_id, filters_json={"project_keys": keys}, created_by=admin.id)
    db.add(row)
    await db.flush()
    return row


async def _refused(call) -> dict:
    with pytest.raises(HTTPException) as refused:
        await call
    assert refused.value.status_code == 409
    return refused.value.detail


async def test_an_intake_reads_through_its_connection_with_the_workspace_deviation(db) -> None:
    ws_a, ws_b = await _workspace(db), await _workspace(db)
    connection = await _connection(db, ["OPS", "RIVER"], [ws_a])
    config = await intake_connection_config(db, await _intake(db, ws_a, connection, ["OPS"]), "jira")
    assert config["jira_token"] == "fake-connection-token" and config["jira_allowed_projects"] == ["OPS", "RIVER"]

    elsewhere = await _refused(intake_connection_config(db, await _intake(db, ws_b, connection, ["OPS"]), "jira"))
    assert elsewhere == {"state": "needs_configuration", "code": "connection_not_available",
                         "reason": "connection_not_available"}

    db.add(ConnectionDeviation(connection_id=connection, workspace_id=ws_a,
                               fields={"tickets": {"scope": {"projects": ["OPS"]}}}))
    await db.flush()
    assert await intake_connection_config(db, await _intake(db, ws_a, connection, ["OPS"]), "jira") is not None
    outside = await _refused(intake_connection_config(db, await _intake(db, ws_a, connection, ["RIVER"]), "jira"))
    assert outside["code"] == "scope_not_allowed" and outside["scopes"] == ["RIVER"]

    deviation = (await db.execute(select(ConnectionDeviation))).scalar_one()
    deviation.fields = {"tickets": {"enabled": False}}
    await db.flush()
    off = await _refused(intake_connection_config(db, await _intake(db, ws_a, connection, ["OPS"]), "jira"))
    assert off["code"] == "connection_use_disabled"

    row = await db.get(ConnectorNamedConnection, connection)
    row.is_active = False
    await db.flush()
    disabled = await _refused(intake_connection_config(db, await _intake(db, ws_a, connection, ["OPS"]), "jira"))
    assert disabled["code"] == "connection_disabled"


async def test_an_unlinked_intake_keeps_the_default_path(db) -> None:
    ws_a = await _workspace(db, {"jira_url": URL, "jira_auth_mode": "bearer_pat", "jira_token": "fake-entry"})
    for connection_id in (None, "default"):
        config = await intake_connection_config(db, await _intake(db, ws_a, connection_id, ["OPS"]), "jira")
        assert config["jira_url"] == URL and config["jira_token"] == "fake-entry"


async def test_a_knowledge_source_reads_through_its_linked_connection(db) -> None:
    ws_a, ws_b = await _workspace(db), await _workspace(db)
    connection = await _connection(db, ["OPS", "RIVER"], [ws_a])
    scope = {"project_keys": ["OPS"]}
    scoped = await resolve_scope_connections(db, kind="jira", project_id=ws_a, scope=scope, connection_id=connection)
    assert set(scoped.connections) == {connection} and scoped.single.secret == "fake-connection-token"

    with pytest.raises(ConnectorError) as elsewhere:
        await resolve_scope_connections(db, kind="jira", project_id=ws_b, scope=scope, connection_id=connection)
    assert elsewhere.value.reason == "connection_not_available"

    # Linked, but the scope item resolves to another connection: refused, never read with that account.
    with pytest.raises(ConnectorError) as mismatch:
        await resolve_scope_connections(db, kind="jira", project_id=ws_a, scope={"project_keys": ["ENG"]},
                                        connection_id=connection)
    assert mismatch.value.reason == "connection_pin_mismatch"

    db.add(ConnectionDeviation(connection_id=connection, workspace_id=ws_a,
                               fields={"knowledge": {"scope": {"projects": ["RIVER"]}}}))
    await db.flush()
    with pytest.raises(ConnectorError) as narrowed:
        await resolve_scope_connections(db, kind="jira", project_id=ws_a, scope=scope, connection_id=connection)
    assert narrowed.value.reason == "scope_not_allowed"
    risk = await resolve_scope_connections(db, kind="jira", project_id=ws_a, scope={"project_keys": ["RIVER"]},
                                           connection_id=connection)
    assert set(risk.connections) == {connection}

    row = await db.get(ConnectorNamedConnection, connection)
    row.is_active = False
    await db.flush()
    with pytest.raises(ConnectorError) as disabled:
        await resolve_scope_connections(db, kind="jira", project_id=ws_a, scope={"project_keys": ["RIVER"]},
                                        connection_id=connection)
    assert disabled.value.reason == "connection_disabled"


async def test_an_unlinked_knowledge_source_keeps_the_resolver_path(db) -> None:
    ws_a = await _workspace(db, {"jira_url": URL, "jira_auth_mode": "bearer_pat", "jira_token": "fake-entry"})
    scoped = await resolve_scope_connections(db, kind="jira", project_id=ws_a, scope={"project_keys": ["OPS"]})
    assert set(scoped.connections) == {"default"} and scoped.single.secret == "fake-entry"


async def test_an_unauthenticated_tool_result_marks_the_connection_failing(db) -> None:
    ws_a = await _workspace(db)
    connection = await _connection(db, ["OPS"], [ws_a], level="write")
    merged = await merge_tool_configs_into_project_config(db, ws_a, {})
    context = ToolContext(user_id="u", project_ids=[ws_a], roles=["admin"], session_id="s", project_config=merged,
                          db=db)

    async def denied(params: dict, ctx) -> dict:
        return {"error": "Jira refused the request.", "status_code": 401}

    out = await routed_execute("get_jira_ticket", {"ticket_id": "OPS-1"}, context, denied)
    assert out["status_code"] == 401
    row = await db.get(ConnectorNamedConnection, connection)
    assert row.state == "failing" and row.state_reason == USE_SENTENCES["agent_tools"]


async def test_the_one_unbound_connection_is_the_default_and_its_own_credential_is_read(db) -> None:
    """The one available connection that binds no key is the Workspace's default connection: the runtime reads its
    account, not the global entry's; disabled, it is no longer the default."""
    from app.services.named_connections.service_config import service_connection_config

    entry = BuiltInToolConfig(tool_name="jira", project_id=None, is_active=True,
                              config={"jira_url": "https://global.example.test", "jira_auth_mode": "bearer_pat",
                                      "jira_allowed_projects": ["OPS"]})
    db.add(entry)
    stored = await set_secret_value(db, tool_name="jira", field_name="jira_token", project_id=None,
                                    value="fake-global")
    entry.config = {**entry.config, "jira_token_secret_ref": stored.id}
    project = Project(name=f"uses-{uuid.uuid4().hex[:8]}")
    db.add(project)
    await db.flush()
    ws = project.id  # no entry of its own: it reads the global entry

    unbound = await _connection(db, [], [ws])
    merged = await merge_tool_configs_into_project_config(db, ws, {})
    assert merged["named_connections"].default_of("jira").id == unbound
    assert merged["jira_url"] == URL and merged["jira_token"] == "fake-connection-token"
    served = await service_connection_config(db, ws, "jira", keys=("OPS",))
    assert (served.connection_id, served.config["jira_url"]) == ("default", URL)
    assert served.config["jira_token"] == "fake-connection-token"

    row = await db.get(ConnectorNamedConnection, unbound)
    row.is_active = False
    await db.flush()
    merged = await merge_tool_configs_into_project_config(db, ws, {})
    assert "named_connections" not in merged or merged["named_connections"].default_of("jira") is None
    assert merged.get("jira_url") != URL and merged.get("jira_token") != "fake-connection-token", (
        "never the disabled account")
