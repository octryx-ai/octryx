"""A page above the limit is answered in slices and changes list with the since parameter, unknown kinds and configurations without version or updated_at are refused, and the admin API samples a draft without saving."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.routes.knowledge.knowledge_source_connectors import router
from app.db import get_db
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.auth import get_current_user
from app.services.knowledge.ledger.errors import InvalidEvidenceRequestError
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.contract import ConnectorError
from app.services.knowledge.sources.sync.rest_config import InvalidRestSourceError
from app.services.knowledge.sources.sync.rest_connection import resolve_rest_connection
from app.services.knowledge.sources.sync.rest_source import RestKnowledgeConnector
from app.services.knowledge.sources.sync.service_run import build_connector, run_connector
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_evidence_seed_support import fetch_user
from tests.support.knowledge_source_sync_custom_rest_support import MAPPING, FakeDocs, _scope, _world, api  # noqa: F401

pytestmark = pytest.mark.usefixtures("public_source_dns")


@pytest.fixture
async def http(db):
    app = FastAPI()
    app.include_router(router)
    state: dict = {"user": None}

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://knowledge.test") as client:
        yield client, state


async def test_a_page_larger_than_the_limit_is_answered_in_slices_and_changes_list_with_the_since_parameter(
        db, api) -> None:  # noqa: F811
    world = await _world(db)
    docs = FakeDocs(page_size=3)
    for number in range(1, 5):
        docs.put(f"D-{number}", f"Doc {number}", "text")
    api.answer = docs.answer
    scope = {**_scope(world, updated_since_param="changed_since"), "media_type": "application/json",
             "arguments": {}, "detail_param": None, "visibility": "restricted", "mapping": MAPPING}
    connection = await resolve_rest_connection(db, world.workspace_id, scope)
    connector = RestKnowledgeConnector(connection, scope=scope, db=db, project_id=world.workspace_id,
                                       actor_id=world.alice_id)

    ids, token = [], None
    while True:
        page = await connector.list_items(token, limit=2)
        assert len(page.items) <= 2
        ids += [item.external_id for item in page.items]
        token = page.next_token
        if token is None:
            break
    assert ids == ["D-1", "D-2", "D-3", "D-4"], "no record is lost or repeated across slices and API pages"

    db.expire_all()  # what the runner's rollback after a refused ingestion does to every loaded row
    content = await connector.fetch(page.items[-1])
    assert content.data.startswith(b"# Doc 4"), "the connector reloads its rows instead of a lazy load"

    await connector.list_changed_items(None, since=datetime(2026, 11, 14, 9, 30, tzinfo=UTC), limit=10)
    assert api.requests[-1].url.params["changed_since"] == "2026-11-14T09:30:00Z"


async def test_an_unknown_kind_is_refused_and_never_read_as_jira(db) -> None:
    world = await _world(db)
    with pytest.raises(InvalidEvidenceRequestError):
        validate_config(connector_key="odd", kind="bogus", project_keys=["OPS"])
    row = KnowledgeSourceConnector(project_id=world.workspace_id, connector_key="odd", kind="bogus", scope={},
                                   created_by=world.alice_id)
    db.add(row)
    await db.flush()
    with pytest.raises(ConnectorError) as refused:
        build_connector(object(), row)
    assert refused.value.reason == "connector_kind_unknown"
    run = await run_connector(db, runtime=world.runtime, authorized=world.alice, row=row, actor_id=world.alice_id)
    assert (run.state, run.reason) == ("needs_configuration", "connector_kind_unknown")


async def test_a_configuration_without_version_or_updated_at_is_refused(db) -> None:
    world = await _world(db)
    with pytest.raises(InvalidRestSourceError) as refused:
        validate_config(connector_key="desk", kind="custom_rest", scope=_scope(world),
                        mapping={"id": "id", "title": "title", "content": "body"})
    assert (refused.value.code, refused.value.field) == ("custom_rest_version_required", "mapping.updated_at")
    with pytest.raises(InvalidEvidenceRequestError):
        validate_config(connector_key="desk", kind="custom_rest", scope=_scope(world), mapping=MAPPING,
                        project_keys=["OPS"])  # another kind's field never applies


async def test_the_admin_api_samples_a_draft_without_saving_and_refuses_an_unscoped_role(db, api, http) -> None:  # noqa: F811
    client, state = http
    world = await _world(db)
    state["user"] = await fetch_user(db, world.alice_id)
    docs = FakeDocs()
    docs.put("D-1", "VPN runbook", "The failover drill for the VPN gateway.")
    docs.put("D-9", "Other team", "Not ours.", group="G2")
    api.answer = docs.answer
    base = f"/api/v1/workspaces/{world.workspace_id}/knowledge/connectors/desk"
    body = {"kind": "custom_rest", "scope": _scope(world), "mapping": MAPPING}

    sample = (await client.post(f"{base}/sample", json=body)).json()

    assert [item["title"] for item in sample["items"]] == ["VPN runbook"]
    assert sample["items"][0]["acl"]["principals"] == [f"role:{world.roles.agent}"]
    assert sample["listing"]["dropped_out_of_scope"] == 1 and sample["last_page"] is True
    assert "failover drill" in sample["first_item_content"]["text"]
    assert sample["first_item_members"] == {"admitted": 1, "unmapped": 0}
    assert (await db.execute(select(func.count()).select_from(KnowledgeSourceConnector).where(
        KnowledgeSourceConnector.project_id == world.workspace_id))).scalar_one() == 0, "a sample saves nothing"

    unscoped = await client.put(base, json={**body, "scope": {**_scope(world), "role": None}})
    assert unscoped.status_code == 409 and unscoped.json()["detail"]["reason"] == "custom_rest_role_required"
    no_version = await client.put(base, json={**body, "mapping": {"id": "id", "title": "title"}})
    assert no_version.status_code == 422 and no_version.json()["detail"]["field"] == "mapping.updated_at"

    # Widening to the whole Workspace is a platform admin's decision, not an author's.
    widened = await client.put(base, json={**body, "scope": {**_scope(world), "visibility": "workspace"}})
    assert widened.status_code == 403 and widened.json()["detail"]["code"] == "rest_source_visibility_admin_only"

    saved = await client.put(base, json=body)
    assert saved.status_code == 200 and saved.json()["acl"]["visibility"] == "restricted"
    status = (await client.get(base)).json()
    assert status["kind"] == "custom_rest" and status["scope"]["mapping"] == MAPPING
