"""Usage lists Workspaces and knowledge connectors by the keys they read, and a knowledge connector's pin to a connection is checked."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog, Project
from app.services.admin.project.named_connection_service import delete_named
from app.services.admin.project.named_connection_view import list_named
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.ledger.errors import InvalidEvidenceRequestError
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.contract import ConnectorError
from app.services.knowledge.sources.sync.scope_connections import resolve_scope_connections
from app.services.knowledge.sources.sync.service import configure_connector
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_evidence_seed_support import fetch_user, seed_member
from tests.support.named_connections_global_support import FAKE_A, FAKE_B, FAKE_G, _body, _no_secret, _save, _workspace

pytestmark = pytest.mark.usefixtures("public_source_dns")


async def test_usage_lists_workspaces_and_knowledge_connectors_by_the_keys_they_read(db) -> None:
    plain = await _workspace(db)
    overriding = await _workspace(db)
    disabled = await _workspace(db, active=False)
    shared = await _save(db, None, _body("global-a", ["SALES", "INFRA"], FAKE_G))
    await _save(db, overriding, _body("own-sales", ["SALES"], FAKE_A))
    user_id = await seed_member(db, workspace_id=plain, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=plain)
    await configure_connector(db, authorized=authorized, actor_id=user_id, config=validate_config(
        connector_key="wiki", kind="confluence", spaces=["SALES", "ENG"]))

    listed = await list_named(db, connector="confluence", project_id=None)

    usage = listed["connections"][0]["usage"]
    by_workspace = {item["id"]: item["scopes"] for item in usage["workspaces"]}
    assert by_workspace == {plain: ["INFRA", "SALES"], overriding: ["INFRA"]}  # not the disabled one
    assert disabled not in by_workspace
    (knowledge,) = usage["knowledge_connectors"]
    assert knowledge["workspace_id"] == plain and knowledge["connector_key"] == "wiki"
    assert knowledge["scopes"] == ["SALES"] and knowledge["pinned"] is False

    seen_here = await list_named(db, connector="confluence", project_id=overriding)
    (inherited,) = seen_here["inherited"]
    assert inherited["id"] == shared["id"] and inherited["read_only"] is True
    assert inherited["served_here"] == ["INFRA"] and inherited["overridden_here"] == ["SALES"]
    _no_secret(seen_here)

    deleted = await delete_named(db, connector="confluence", project_id=None, connection_id=shared["id"],
                                 actor_id=user_id)
    assert {item["id"] for item in deleted["used_by"]["workspaces"]} == {plain, overriding}
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "admin.named_connection.deleted"))).scalars()
    details = [row.details for row in audit if shared["id"] in str(row.resource_id)]
    assert details and details[0]["used_by"]["knowledge_connectors"][0]["connector_key"] == "wiki"
    _no_secret(details)


# --- Knowledge connector pinned by id -------------------------------------------------------------------


async def test_a_knowledge_connector_pinned_to_a_connection_is_refused_when_its_items_resolve_elsewhere(db) -> None:
    workspace_id = await _workspace(db)
    shared = await _save(db, None, _body("global-a", ["SALES"], FAKE_G))
    other = await _save(db, None, _body("global-b", ["INFRA"], FAKE_B))
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)

    def pinned(connection_id: str, spaces=("SALES",)):
        return validate_config(connector_key="wiki", kind="confluence", spaces=list(spaces),
                               connection_id=connection_id)

    row = await configure_connector(db, authorized=authorized, config=pinned(shared["id"]), actor_id=user_id)
    assert row.scope["connection_id"] == shared["id"]
    usage = (await list_named(db, connector="confluence", project_id=None))["connections"]
    assert {c["name"]: [k["pinned"] for k in c["usage"]["knowledge_connectors"]] for c in usage} == {
        "global-a": [True], "global-b": []}

    # A stale pin (to global-b while SALES resolves to global-a): global-a is not its account (runs are refused),
    # global-b lists it as pinned with a mismatch.
    row.scope = {**row.scope, "connection_id": other["id"]}
    await db.flush()
    stale = {c["name"]: c["usage"]["knowledge_connectors"]
             for c in (await list_named(db, connector="confluence", project_id=None))["connections"]}
    assert stale["global-a"] == []
    assert [(k["pinned"], k["pin_mismatch"], k["scopes"]) for k in stale["global-b"]] == [(True, True, [])]
    row.scope = {**row.scope, "connection_id": shared["id"]}
    await db.flush()

    with pytest.raises(ConnectorError) as refused:  # INFRA resolves to global-b, not to the pin
        await configure_connector(db, authorized=authorized, config=pinned(shared["id"], ("SALES", "INFRA")),
                                  actor_id=user_id)
    assert refused.value.reason == "connection_pin_mismatch"
    with pytest.raises(ConnectorError):
        await configure_connector(db, authorized=authorized, config=pinned(other["id"]), actor_id=user_id)

    await delete_named(db, connector="confluence", project_id=None, connection_id=shared["id"], actor_id=None)
    with pytest.raises(ConnectorError) as gone:  # never read with whatever serves SALES now
        await resolve_scope_connections(db, kind="confluence", project_id=workspace_id, scope=dict(row.scope))
    assert gone.value.reason == "connection_pin_mismatch"


def test_a_pin_is_only_for_connection_connectors_and_well_formed() -> None:
    assert "connection_id" not in validate_config(connector_key="wiki", kind="confluence", spaces=["SALES"]).scope
    assert validate_config(connector_key="wiki", kind="confluence", spaces=["SALES"],
                           connection_id="default").scope["connection_id"] == "default"
    with pytest.raises(InvalidEvidenceRequestError):
        validate_config(connector_key="wiki", kind="confluence", spaces=["SALES"], connection_id="../x")
    with pytest.raises(InvalidEvidenceRequestError):
        validate_config(connector_key="repo", kind="git_repository", fetch_mode="remote_git",
                        repository_url="https://github.com/a/b", ref="main", connection_id="default")


async def test_a_project_without_the_connector_is_not_a_user(db) -> None:
    project = Project(name=f"bare-{uuid.uuid4().hex[:6]}")
    db.add(project)
    await db.flush()
    shared = await _save(db, None, _body("global-a", ["SALES"], FAKE_G))
    usage = (await list_named(db, connector="confluence", project_id=None))["connections"]
    assert [c["usage"]["workspaces"] for c in usage if c["id"] == shared["id"]] == [[]]
