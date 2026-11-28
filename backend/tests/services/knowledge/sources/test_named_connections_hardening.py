"""Named connections, merge and race hardening."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

import app.services.admin.project.named_connection_service as service
from app.models import BuiltInToolConfig, ConnectorNamedConnection
from app.models.security.secret import StoredSecret
from app.services.admin.project.named_connection_service import save_named
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.contract import ConnectorError
from app.services.knowledge.sources.sync.owner_rules import SourceRuleRefusedError
from app.services.knowledge.sources.sync.service import configure_connector
from app.services.named_connections.routes_model import NAMED_CONNECTIONS_KEY
from app.services.named_connections.tool_routing import routed_execute
from app.services.named_connections.workspace_routes import workspace_routes
from app.tools.context import ToolContext
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace

pytestmark = pytest.mark.usefixtures("public_source_dns")

WIKI = "https://wiki.example.test/wiki"
FAKE_OWN, FAKE_GLOBAL, FAKE_DEFAULT = "fake-own-pat-1", "fake-global-pat-2", "fake-default-pat-3"


def _body(name: str, scopes: list[str], token: str) -> dict:
    return {"name": name, "bound_scopes": scopes, "confluence_url": WIKI, "confluence_auth_mode": "bearer_pat",
            "confluence_token": token}


async def _workspace(db) -> str:
    workspace_id = await seed_workspace(db)
    db.add(BuiltInToolConfig(tool_name="confluence", project_id=workspace_id, is_active=True, config={
        "confluence_url": WIKI, "confluence_auth_mode": "bearer_pat", "confluence_token": FAKE_DEFAULT,
        "confluence_allowed_spaces": [{"space_key": "ENG", "enabled": True}],
    }))
    await db.flush()
    return workspace_id


async def _save(db, project_id, body) -> dict:
    return await save_named(db, connector="confluence", project_id=project_id, payload=body, actor_id=None)


async def test_same_name_pair_overridden_key_and_secret_free_routes_route_each_call_to_its_own_secret(db) -> None:
    workspace_id = await _workspace(db)
    own = await _save(db, workspace_id, _body("client-a", ["SALES"], FAKE_OWN))
    shared = await _save(db, None, _body("client-a", ["SALES", "INFRA"], FAKE_GLOBAL))

    routes = await workspace_routes(db, workspace_id, ("confluence",), secrets=False)
    assert [(c.id, set(c.bound_scopes)) for c in routes.of("confluence")] == [
        (own["id"], {"SALES"}), (shared["id"], {"INFRA"})]
    assert all("confluence_token" not in c.config and c.source is not None for c in routes.of("confluence"))

    base = {"confluence_url": WIKI, "confluence_auth_mode": "bearer_pat", "confluence_token": FAKE_DEFAULT,
            "confluence_allowed_spaces": [{"space_key": "ENG", "enabled": True}], NAMED_CONNECTIONS_KEY: routes}
    context = ToolContext(user_id="u", project_ids=[workspace_id], roles=["admin"], session_id="s",
                          project_config=base, db=db)
    seen: list[tuple[str, tuple]] = []

    async def execute(params, ctx):
        config = ctx.project_config
        seen.append((config.get("confluence_token"), tuple(map(str, config["confluence_allowed_spaces"]))))
        return {"results": [], "total": 0}

    await routed_execute("get_confluence_page", {"space_key": "sales", "page_id": "1"}, context, execute)
    await routed_execute("get_confluence_page", {"space_key": "INFRA", "page_id": "2"}, context, execute)
    assert seen == [(FAKE_OWN, ("SALES",)), (FAKE_GLOBAL, ("INFRA",))]

    seen.clear()
    fanned = await routed_execute("search_confluence", {"query": "x"}, context, execute)
    assert seen[:2] == [(FAKE_OWN, ("SALES",)), (FAKE_GLOBAL, ("INFRA",))]
    assert seen[2][0] == FAKE_DEFAULT and "SALES" not in str(seen[2][1])
    assert [s["connection_id"] for s in fanned["connections"]] == [own["id"], shared["id"], "default"]


async def test_a_concurrent_save_of_the_same_name_is_a_409_and_stores_no_secret(db, monkeypatch) -> None:
    workspace_id = await _workspace(db)

    async def no_check(*args, **kwargs):  # the race: the other save is not visible to the pre-check yet
        return None

    monkeypatch.setattr(service, "_check_scope_rules", no_check)
    db.add(ConnectorNamedConnection(id=str(uuid.uuid4()), tool_name="confluence", project_id=workspace_id,
                                    scope_key=workspace_id, name="Client-A", config={}, bound_scopes=["X"]))
    await db.commit()

    with pytest.raises(HTTPException) as refused:
        await _save(db, workspace_id, _body("client-a", ["SALES"], FAKE_OWN))

    assert refused.value.status_code == 409
    assert refused.value.detail["code"] == "named_connection_name_taken"
    stored = (await db.execute(select(StoredSecret).where(StoredSecret.tool_name == "confluence"))).scalars().all()
    assert [entry for entry in stored if "#" in str(entry.field_name)] == []


async def test_a_pin_must_name_a_connection_the_workspace_can_use(db) -> None:
    workspace_id = await _workspace(db)
    other_workspace = await _workspace(db)
    usable = await _save(db, None, _body("global-a", ["SALES"], FAKE_GLOBAL))
    foreign = await _save(db, other_workspace, _body("theirs", ["SALES"], FAKE_OWN))
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)

    def pinned(connection_id: str):
        return validate_config(connector_key="wiki", kind="confluence", spaces=["SALES"], connection_id=connection_id)

    row = await configure_connector(db, authorized=authorized, config=pinned(usable["id"]), actor_id=user_id)
    assert row.scope["connection_id"] == usable["id"]
    with pytest.raises(ConnectorError) as refused:
        await configure_connector(db, authorized=authorized, config=pinned(str(uuid.uuid4())), actor_id=user_id)
    assert refused.value.reason == "connection_pin_unknown"
    with pytest.raises(SourceRuleRefusedError) as foreign_refused:
        await configure_connector(db, authorized=authorized, config=pinned(foreign["id"]), actor_id=user_id)
    assert foreign_refused.value.code == "source_connection_not_granted"
