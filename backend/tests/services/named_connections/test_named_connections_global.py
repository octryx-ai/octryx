"""Global named connections and their ids: told apart by id, Workspace bindings override global ones, and no
response carries a secret value or a ``*_secret_ref``."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import ConnectorNamedConnection
from app.services.knowledge.sources.sync.scope_connections import resolve_scope_connections
from app.services.named_connections.routes_model import (
    NAMED_CONNECTIONS_KEY,
    NamedConnectionRoutes,
    ResolvedNamedConnection,
)
from app.services.named_connections.tool_routing import routed_execute
from app.services.named_connections.workspace_routes import workspace_routes
from app.tools.context import ToolContext
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.support.named_connections_global_support import (
    FAKE_A,
    FAKE_B,
    FAKE_G,
    OTHER_WIKI,
    PANEL,
    _body,
    _login,
    _save,
    _workspace,
)

pytestmark = pytest.mark.usefixtures("public_source_dns")


def _jira(name: str, scope: str, ref: str, keys: set[str], token: str) -> ResolvedNamedConnection:
    return ResolvedNamedConnection(ref, "jira", name, scope, frozenset(keys),
                                   {"jira_url": "https://jira.example.test", "jira_token": token})


async def test_a_workspace_and_a_global_connection_with_one_name_each_read_their_own_space(db) -> None:
    workspace_id = await _workspace(db)
    own = await _save(db, workspace_id, _body("client-a", ["SALES"], FAKE_A))
    shared = await _save(db, None, _body("client-a", ["INFRA"], FAKE_G, url=OTHER_WIKI))

    scoped = await resolve_scope_connections(
        db, kind="confluence", project_id=workspace_id, scope={"spaces": ["SALES", "INFRA"]}
    )

    assert scoped.by_key == {"SALES": own["id"], "INFRA": shared["id"]}
    assert scoped.connections[own["id"]].secret == FAKE_A
    assert scoped.connections[shared["id"]].secret == FAKE_G
    assert scoped.connections[shared["id"]].base_url.startswith("https://other.example.test")
    assert scoped.single is None  # two accounts: each space is read by its own unit
    assert scoped.described() == {"SALES": f"client-a ({own['id']})", "INFRA": f"client-a ({shared['id']})"}


async def test_a_call_over_two_same_named_connections_is_refused_and_each_key_uses_its_own_account() -> None:
    own = _jira("ops", "workspace", "id-own", {"OPS"}, FAKE_A)
    shared = _jira("ops", "global", "id-global", {"RIVER"}, FAKE_G)
    config = {"jira_url": "https://jira.example.test", NAMED_CONNECTIONS_KEY: NamedConnectionRoutes((own, shared))}
    context = ToolContext(user_id="u", project_ids=["p"], roles=["admin"], session_id="s", project_config=config)
    seen: list[dict] = []

    async def execute(params, ctx):
        seen.append(ctx.project_config)
        return {"ok": True}

    refused = await routed_execute("add_issues_to_sprint", {"ticket_ids": ["OPS-1", "RIVER-2"]}, context, execute)
    assert refused["code"] == "scope_spans_connections" and seen == []

    await routed_execute("get_jira_ticket", {"ticket_id": "RIVER-2"}, context, execute)
    await routed_execute("get_jira_ticket", {"ticket_id": "OPS-1"}, context, execute)
    assert [config["jira_token"] for config in seen] == [FAKE_G, FAKE_A]


async def test_a_global_connection_serves_only_the_keys_the_workspace_does_not_bind(db) -> None:
    workspace_id = await _workspace(db)
    await _save(db, workspace_id, _body("own-sales", ["SALES"], FAKE_A))
    partly = await _save(db, None, _body("global-sales-infra", ["SALES", "INFRA"], FAKE_G))
    await _save(db, None, _body("global-ops", ["OPS"], FAKE_B))
    await _save(db, workspace_id, _body("own-ops", ["ops"], FAKE_A))

    routes_ = await workspace_routes(db, workspace_id, ("confluence",))

    assert [(c.name, c.scope, set(c.bound_scopes)) for c in routes_.of("confluence")] == [
        ("own-ops", "workspace", {"OPS"}),
        ("own-sales", "workspace", {"SALES"}),
        ("global-sales-infra", "global", {"INFRA"}),  # SALES is the Workspace's: not searched with this account
    ]  # "global-ops" is fully overridden here: no route at all
    assert routes_.match("confluence", "SALES").name == "own-sales"
    assert routes_.match("confluence", "infra").id == partly["id"]


async def test_names_are_unique_per_connector_and_scope_regardless_of_case(client, db) -> None:
    await _login(client)
    url = f"{PANEL}/connectors/confluence/named-connections"
    assert (await client.post(url, json=_body("Client-A", ["SALES"], FAKE_A))).status_code == 201

    taken = await client.post(url, json=_body("client-a", ["INFRA"], FAKE_B))

    assert taken.status_code == 409 and taken.json()["detail"]["code"] == "named_connection_name_taken"
    # The database refuses it too (unique on lower(name)), whatever path writes the row.
    db.add(ConnectorNamedConnection(id=str(uuid.uuid4()), tool_name="confluence", project_id=None,
                                    scope_key="global", name="CLIENT-A", config={}, bound_scopes=["X"]))
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()
