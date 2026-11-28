"""Knowledge › Sources for Workspace owners, the source ACL switch, the REST source catalog and the sample excerpt."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.routes.knowledge.knowledge_source_connectors import router as connectors_router
from app.api.routes.knowledge.knowledge_source_settings import router as settings_router
from app.db import get_db
from app.models import AuditLog, Project, RestApiDefinition, RestApiOperation, User
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.auth import get_current_user
from app.services.knowledge.sources.sync.acl_switch import ENFORCE_AUDIT_ACTION
from app.services.rest_connector.connections import create_connection
from app.services.rest_connector.definitions import create_definition, update_operation
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.support.knowledge_source_sync_custom_rest_support import MAPPING, OPERATIONS, FakeDocs, _run, _scope, _world
from tests.support.rest_connector_support import API, SECRET, recorded_api

pytestmark = pytest.mark.usefixtures("public_source_dns")


@pytest.fixture
def api(monkeypatch):
    return recorded_api(monkeypatch)


@pytest.fixture
async def http(db):
    app = FastAPI()
    app.include_router(connectors_router)
    app.include_router(settings_router)
    state: dict = {"user": None}

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://knowledge.test") as client:
        yield client, state


async def _owner(db, workspace_id: str, name: str) -> User:
    user_id = await seed_member(db, workspace_id=workspace_id, role="owner", username=name)
    await db.commit()
    return await fetch_user(db, user_id)


async def _platform_admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def test_a_workspace_owner_runs_restricted_sources_but_not_workspace_visibility_or_the_switch(
        db, api, http, monkeypatch) -> None:
    client, state = http
    world = await _world(db)
    monkeypatch.setattr("app.api.routes.knowledge.knowledge_source_connectors.get_evidence_runtime", lambda: world.runtime)
    owner = await _owner(db, world.workspace_id, f"carol{world.key}")
    docs = FakeDocs()
    docs.put("D-1", "VPN runbook", "The failover drill for the VPN gateway.")
    api.answer = docs.answer
    state["user"] = owner
    base = f"/api/v1/workspaces/{world.workspace_id}/knowledge"
    body = {"kind": "custom_rest", "scope": _scope(world), "mapping": MAPPING}

    assert (await client.post(f"{base}/connectors/desk/sample", json=body)).status_code == 200
    saved = await client.put(f"{base}/connectors/desk", json=body)
    assert saved.status_code == 200 and saved.json()["acl"]["visibility"] == "restricted"
    assert (await client.post(f"{base}/connectors/desk/runs")).status_code == 200
    assert [row["connector_key"] for row in (await client.get(f"{base}/connectors")).json()["connectors"]] == ["desk"]

    widened = await client.put(f"{base}/connectors/desk",
                               json={**body, "scope": {**_scope(world), "visibility": "workspace"}})
    assert widened.status_code == 403 and widened.json()["detail"]["code"] == "rest_source_visibility_admin_only"
    switch = await client.put(f"{base}/source-acl", json={"enforce": False, "reason": "mine"})
    assert switch.status_code == 403 and switch.json()["detail"]["code"] == "source_acl_enforce_admin_only"
    assert (await client.get(f"{base}/source-acl")).status_code == 403
    assert (await db.get(Project, world.workspace_id)).config["knowledge_source_acl"] == {"enforce": True}

    stranger = await _owner(db, await seed_workspace(db), f"dave{world.key}")
    state["user"] = stranger
    for method, path, payload in (("GET", "/connectors", None), ("GET", "/connectors/desk", None),
                                  ("PUT", "/connectors/other", body), ("POST", "/connectors/desk/sample", body),
                                  ("POST", "/connectors/desk/runs", None), ("GET", "/rest-sources", None),
                                  ("GET", "/source-acl", None)):
        answer = await client.request(method, f"{base}{path}", json=payload)
        assert answer.status_code == 404, (method, path, answer.status_code)


async def test_the_switch_needs_a_reason_counts_the_release_is_audited_and_lets_the_next_run_ingest(
        db, api, http, monkeypatch) -> None:
    client, state = http
    world = await _world(db, enforce=False)
    monkeypatch.setattr("app.api.routes.knowledge.knowledge_source_connectors.get_evidence_runtime", lambda: world.runtime)
    docs = FakeDocs()
    docs.put("D-1", "VPN runbook", "The failover drill for the VPN gateway.")
    api.answer = docs.answer
    state["user"] = await fetch_user(db, world.alice_id)
    base = f"/api/v1/workspaces/{world.workspace_id}/knowledge"
    body = {"kind": "custom_rest", "scope": _scope(world), "mapping": MAPPING}
    assert (await client.put(f"{base}/connectors/desk", json=body)).status_code == 200
    run = (await client.post(f"{base}/connectors/desk/runs")).json()
    assert run["report"]["withheld_reasons"] == {"restricted_acl": 1}

    admin = await _platform_admin(db)
    state["user"] = admin
    state_before = (await client.get(f"{base}/source-acl")).json()
    assert state_before["enforce"] is False and state_before["released_when_enabled"] == 1
    assert (await client.put(f"{base}/source-acl", json={"enforce": True, "reason": "  "})).status_code == 422
    assert (await client.put(f"{base}/source-acl", json={"enforce": True})).status_code == 422

    dry = (await client.put(f"{base}/source-acl", json={"enforce": True, "reason": "check", "dry_run": True})).json()
    assert dry["dry_run"] is True and dry["enforce"] is False and dry["released_when_enabled"] == 1
    audits = select(AuditLog).where(AuditLog.action == ENFORCE_AUDIT_ACTION, AuditLog.resource_id == world.workspace_id)
    assert (await db.execute(audits)).scalars().all() == [], "a dry run changes and records nothing"

    switched = await client.put(f"{base}/source-acl", json={"enforce": True, "reason": "Desk docs go live (OPS-12)"})
    assert switched.status_code == 200 and switched.json()["changed"] is True
    [audit] = (await db.execute(audits)).scalars().all()
    assert audit.user_id == admin.id
    assert audit.details == {"workspace_id": world.workspace_id, "before": False, "after": True,
                             "reason": "Desk docs go live (OPS-12)", "withheld_restricted_items": 1}
    assert (await client.get(f"{base}/source-acl")).json()["enforce"] is True
    again = (await client.put(f"{base}/source-acl", json={"enforce": True, "reason": "twice"})).json()
    assert again["changed"] is False and len((await db.execute(audits)).scalars().all()) == 1

    run = await _run(db, world, (await db.execute(select(KnowledgeSourceConnector).where(
        KnowledgeSourceConnector.project_id == world.workspace_id))).scalar_one())
    assert run.report["created"] == 1 and run.report.get("withheld_reasons", {}) == {}


async def test_the_catalog_shows_what_the_workspace_can_read_and_no_secret_or_foreign_definition(
        db, api, http) -> None:
    client, state = http
    world = await _world(db)
    owner = await _owner(db, world.workspace_id, f"erin{world.key}")
    other_workspace = await seed_workspace(db)
    admin = await _platform_admin(db)
    row = (await db.execute(select(RestApiDefinition).where(RestApiDefinition.key == world.key))).scalar_one()
    listing = (await db.execute(select(RestApiOperation).where(RestApiOperation.definition_id == row.id,
                                                               RestApiOperation.op_key == "list_docs"))).scalar_one()
    await update_operation(db, row.id, listing.id, {"params_overlay": {"changed_since": {"value": "FIXED-VALUE-9"}}})
    foreign = await create_definition(db, {"key": f"f{world.key}", "name": "Foreign desk", "auth": {"scheme": "bearer"},
                                           "operations": OPERATIONS}, actor_user_id=admin.id)
    await create_connection(db, foreign["id"], {"base_url": API, "token": SECRET, "project_id": other_workspace})
    granted_elsewhere = await create_definition(db, {"key": f"g{world.key}", "name": "Elsewhere", "auth": {
        "scheme": "bearer"}, "operations": OPERATIONS}, actor_user_id=admin.id)
    await create_connection(db, granted_elsewhere["id"], {"base_url": API, "token": SECRET})
    await update_operation(db, granted_elsewhere["id"], granted_elsewhere["operations"][1]["id"], {
        "enabled": True, "grants": [{"role": world.roles.agent, "workspace_id": other_workspace}]})
    await db.commit()
    url = f"/api/v1/workspaces/{world.workspace_id}/knowledge/rest-sources"

    state["user"] = owner
    answer = await client.get(url)
    assert answer.status_code == 200
    catalog = answer.json()
    [desk] = [entry for entry in catalog["definitions"] if entry["key"] in (world.key, foreign["key"],
                                                                            granted_elsewhere["key"])]
    assert desk["key"] == world.key and desk["connection"] == "global"
    operations = {operation["op_key"]: operation for operation in desk["operations"]}
    assert operations["list_docs"]["records_path"] == "items" and operations["list_docs"]["paginated"] is True
    assert operations["list_docs"]["role_required"] is True and world.roles.agent in operations["list_docs"]["roles"]
    assert operations["get_doc"]["detail_candidate"] is True
    params = {param["name"]: param for param in operations["list_docs"]["parameters"]}
    assert params["changed_since"]["fixed"] is True and params["group"]["scoped"] is True
    text = json.dumps(catalog)
    for hidden in (SECRET, "FIXED-VALUE-9", API, "G1", "bearer"):
        assert hidden not in text, hidden

    member = await fetch_user(db, await seed_member(db, workspace_id=world.workspace_id, role="member"))
    state["user"] = member
    assert (await client.get(url)).status_code == 403

    state["user"] = admin
    everything = {entry["key"]: entry for entry in (await client.get(url)).json()["definitions"]}
    assert everything[foreign["key"]]["connection"] is None
    elsewhere = everything[granted_elsewhere["key"]]["operations"]
    assert elsewhere and not any(op["usable"] or op["roles"] for op in elsewhere), "another Workspace's grant"


async def test_each_sample_item_has_a_masked_excerpt_of_at_most_300_characters_without_fence_markers(
        db, api, http) -> None:
    client, state = http
    world = await _world(db)
    token = "sk-proj-" + "Ab12Cd34Ef56Gh78Ij90Kl12Mn34Op56"
    docs = FakeDocs()
    docs.put("D-1", "VPN runbook", "<<<knowledge 0123456789abcdef>>>\nRotate the gateway key " + token + " first. "
             + "The failover drill for the VPN gateway. " * 20)
    docs.put("D-2", "Short note", "Call the duty officer.")
    api.answer = docs.answer
    state["user"] = await fetch_user(db, world.alice_id)
    body = {"kind": "custom_rest", "scope": _scope(world), "mapping": MAPPING}

    sample = (await client.post(f"/api/v1/workspaces/{world.workspace_id}/knowledge/connectors/desk/sample",
                                json=body)).json()

    long, short = sample["items"]
    assert long["excerpt"].startswith("Rotate the gateway key") and long["excerpt"].endswith("…")
    assert len(long["excerpt"]) <= 300 and "<<<" not in long["excerpt"]
    assert token not in long["excerpt"] and "sk-proj-Ab12" not in long["excerpt"]
    assert short["excerpt"] == "Call the duty officer."
    assert token not in json.dumps(sample), "the first item's longer text is masked too"
