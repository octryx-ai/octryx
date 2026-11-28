"""Contract (Confluence page-tree scope, root-frozen): a connector can sync a page and its descendants."""

from __future__ import annotations

from datetime import UTC

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.routes.knowledge import knowledge_source_connectors as routes
from app.api.routes.knowledge._knowledge_connector_http import ConnectorConfigBody
from app.models.project.knowledge_source_sync import KnowledgeSourceSyncItem
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.confluence_scope import InvalidPageTreeError
from app.services.knowledge.sources.sync.contract import ConnectorError
from app.services.knowledge.sources.sync.service import configure_connector
from app.time_utils import utc_now
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_evidence_seed_support import fetch_user
from tests.knowledge_source_sync_support import WIKI, _setup
from tests.services.knowledge.sources.test_confluence_cloud_freshness import _cloud, _origins
from tests.support.confluence_cloud_freshness_corrections_support import HIDDEN, _run

pytestmark = pytest.mark.usefixtures("public_source_dns")

TREE = {"space_key": "ENG", "root_page_id": "100"}


async def _tree_connector(db, setup, trees=(TREE,)):
    authorized, user_id, _, _ = setup
    config = validate_config(connector_key="ops", kind="confluence", page_trees=[dict(tree) for tree in trees],
                             products=["acme-orders"])
    await configure_connector(db, authorized=authorized, config=config, actor_id=user_id)


def _space(stub) -> None:
    stub.put("50", "Home", "<p>Space home.</p>")
    stub.put("100", "Runbooks", "<p>Root.</p>", parent="50")
    stub.put("101", "Failover", "<p>Child.</p>", parent="100")
    stub.put("102", "Failover drill", "<p>Grandchild.</p>", parent="101")
    stub.put("200", "Elsewhere", "<p>Outside.</p>", parent="50")


async def _states(db, setup) -> dict[str, str]:
    rows = await db.execute(select(KnowledgeSourceSyncItem.external_id, KnowledgeSourceSyncItem.state).where(
        KnowledgeSourceSyncItem.connector_id == setup[3].id))
    return dict(rows.all())


async def test_a_tree_lists_its_nested_pages_and_retires_what_moves_out(db) -> None:
    setup = await _setup(db, kind="confluence")
    await _tree_connector(db, setup)
    stub = _cloud()
    _space(stub)

    first = await _run(db, setup, stub)
    assert first.state == "completed" and first.report["created"] == 3 and first.report["listed"] == 3
    assert await _origins(db, setup[0].project_id) == {
        f"{WIKI}/spaces/ENG/pages/100/Runbooks",
        f"{WIKI}/spaces/ENG/pages/101/Failover",
        f"{WIKI}/spaces/ENG/pages/102/Failover+drill",
    }
    assert not any(request == "GET /wiki/rest/api/content" for request in stub.requests), "no whole-space listing"

    stub.move("101", "200")  # moved out of the tree, with its own child; no version change
    moved = await _run(db, setup, stub)
    assert moved.report["retired"] == 2 and moved.report["unchanged"] == 1
    states = await _states(db, setup)
    assert (states["101"], states["102"], states["100"]) == ("retired", "retired", "ingested")


async def test_the_tree_follows_the_header_pass_acl_and_change_rules(db) -> None:
    setup = await _setup(db, kind="confluence")
    await _tree_connector(db, setup)
    stub = _cloud()
    stub.accounts = {HIDDEN: None}
    _space(stub)
    await _run(db, setup, stub)

    stub.clock = utc_now().replace(tzinfo=UTC)
    stub.edit("102", body="<p>Grandchild v2.</p>")
    stub.edit("200", body="<p>Outside v2.</p>")
    stub.pages["50"]["account"] = HIDDEN  # restricted above the tree: inherited by every tree page
    seen: list = []
    run = await _run(db, setup, stub, trigger="scheduled", seen=seen)
    cql = [url.params["cql"] for url in seen if url.path.endswith("/content/search")]
    assert cql and all("ancestor = 100" in query for query in cql), "changes are asked for the tree only"
    assert any("lastmodified" in query for query in cql) and run.report["mode"] == "incremental"
    assert run.report["withheld"] == 3 and set((await _states(db, setup)).values()) == {"withheld"}


async def test_the_trees_space_must_be_allowed_and_bad_trees_are_coded(db) -> None:
    setup = await _setup(db, kind="confluence")
    with pytest.raises(ConnectorError) as refused:
        await _tree_connector(db, setup, trees=({"space_key": "DEMO", "root_page_id": "100002"},))
    assert refused.value.reason == "scope_not_allowed"

    for trees, code in (
        ("ENG", "page_trees_invalid"),
        ([{"space_key": "ENG"}], "page_trees_invalid"),
        ([{**TREE, "title": "x"}], "page_trees_invalid"),
        ([{"space_key": "EN G", "root_page_id": "1"}], "page_tree_space_invalid"),
        ([{"space_key": "ENG", "root_page_id": 100}], "page_tree_root_invalid"),
        ([{"space_key": "ENG", "root_page_id": "https://wiki.example.test/wiki/pages/100"}], "page_tree_root_invalid"),
        ([TREE, {"space_key": "ENG", "root_page_id": "100"}], "page_tree_duplicate"),
    ):
        with pytest.raises(InvalidPageTreeError) as invalid:
            validate_config(connector_key="ops", kind="confluence", page_trees=trees)
        assert invalid.value.code == code, trees
    with pytest.raises(InvalidPageTreeError) as listed:
        validate_config(connector_key="ops", kind="confluence", spaces=["ENG"], page_trees=[TREE])
    assert listed.value.code == "page_tree_in_listed_space"
    with pytest.raises(InvalidPageTreeError) as jira:
        validate_config(connector_key="ops", kind="jira", project_keys=["OPS"], page_trees=[TREE])
    assert jira.value.code == "page_trees_confluence_only"
    assert validate_config(connector_key="ops", kind="confluence", page_trees=[TREE]).scope == {
        "spaces": [], "page_trees": [TREE]}
    assert validate_config(connector_key="ops", kind="confluence", spaces=["ENG"]).scope == {"spaces": ["ENG"]}


async def test_the_route_answers_a_refused_tree_with_a_coded_422(db) -> None:
    authorized, user_id, _, _ = await _setup(db, kind="confluence")
    user = await fetch_user(db, user_id)
    body = ConnectorConfigBody(kind="confluence", page_trees=[{"space_key": "ENG", "root_page_id": "x"}])
    with pytest.raises(HTTPException) as refused:
        await routes.configure_workspace_connector(authorized.project_id, "tree", body, user, db)
    assert refused.value.status_code == 422
    assert refused.value.detail == {"state": "invalid_request", "reason": "page_tree_root_invalid", "field": "page_trees"}
