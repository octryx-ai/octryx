"""The evidence tool's scope is server-owned: its schema exposes no scope, it ignores a model-supplied scope, refuses projects outside the run, bad limits and a missing workspace, and leaks no dependency detail."""

from __future__ import annotations

import pytest

from app.services.knowledge.access.authorization import authorize_tool_workspace, authorize_workspace
from app.services.knowledge.ledger.errors import WorkspaceNotAccessibleError
from app.services.knowledge.projection.projector import EvidenceProjector
from app.tools.definitions.knowledge_evidence import MAX_TOOL_RESULT_LIMIT
from app.tools.knowledge_evidence.search import KnowledgeSearchTool
from app.tools.registry import TOOL_REGISTRY
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import (
    fetch_user,
    new_workspace_id,
    seed_member,
    seed_outsider,
    seed_workspace,
    tool_context,
)
from tests.support.knowledge_evidence_index_support import FakeEvidenceIndex
from tests.support.knowledge_evidence_isolation_support import _authorized, _ingest
from tests.support.knowledge_evidence_s3_support import FakeS3Client


def test_the_tool_schema_exposes_no_workspace_or_project_property():
    from app.tools.definitions import get_all_definitions

    schema = get_all_definitions()["knowledge_search"]["function"]["parameters"]["properties"]
    assert set(schema) == {"query", "limit", "products", "version"}
    for forbidden in ("project_id", "workspace_id", "workspace", "database", "bucket"):
        assert forbidden not in schema
    assert "knowledge_search" in TOOL_REGISTRY


async def test_the_tool_ignores_a_model_supplied_scope_argument(db):
    owned_id = await seed_workspace(db)
    foreign_id = await seed_workspace(db)
    owner_id = await seed_member(db, workspace_id=owned_id, role="admin")
    owner = await fetch_user(db, owner_id)
    owned = await authorize_workspace(db, current_user=owner, workspace_id=owned_id)
    foreign = await _authorized(db, foreign_id)
    runtime, _, evidence_index = build_runtime()
    projector = EvidenceProjector(runtime)

    await _ingest(db, runtime, owned, payload=b"Owned workspace mentions datacenter Zurich.\n")
    await _ingest(db, runtime, foreign, payload=b"Foreign workspace mentions datacenter Lugano.\n")
    for _ in range(2):
        await projector.project_once(db, worker_id="worker-a")

    from tests.knowledge_runtime_support import set_evidence_runtime

    set_evidence_runtime(runtime)
    try:
        context = tool_context(user_id=owner_id, project_id=owned_id, project_ids=[owned_id], db=db)
        result = await KnowledgeSearchTool().execute(
            {
                "query": "datacenter",
                "project_id": foreign_id,
                "workspace_id": foreign_id,
                "database": foreign.workspace.canonical,
            },
            context,
        )
    finally:
        set_evidence_runtime(None)

    assert result["state"] == "ok"
    assert result["workspace_id"] == owned_id
    assert [item["text"] for item in result["evidence"]] == ["Owned workspace mentions datacenter Zurich."]


async def test_the_tool_refuses_a_context_project_outside_the_runs_scope(db):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")

    with pytest.raises(WorkspaceNotAccessibleError):
        await authorize_tool_workspace(
            db, user_id=user_id, project_id=workspace_id, allowed_project_ids=[new_workspace_id()]
        )


async def test_the_tool_reports_a_fixed_state_and_leaks_no_dependency_detail(db):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    runtime, _, _ = build_runtime(s3=FakeS3Client(unavailable=True), index=FakeEvidenceIndex(unavailable=True))
    from tests.knowledge_runtime_support import set_evidence_runtime

    set_evidence_runtime(runtime)
    try:
        context = tool_context(user_id=user_id, project_id=workspace_id, project_ids=[workspace_id], db=db)
        result = await KnowledgeSearchTool().execute({"query": "datacenter"}, context)
    finally:
        set_evidence_runtime(None)

    assert result["state"] == "no_sources"
    rendered = repr(result)
    for forbidden in ("127.0.0.1", "octryx_ws_", "knowledge_evidence_index", "plainto_tsquery", "sha256/", "octryx-knowledge-test"):
        assert forbidden not in rendered


async def test_the_tool_needs_a_workspace_in_context(db):
    user_id = await seed_outsider(db)
    context = tool_context(user_id=user_id, project_id=None, project_ids=[], db=db)
    result = await KnowledgeSearchTool().execute({"query": "datacenter"}, context)
    assert result["state"] == "not_found"


async def test_the_tool_refuses_a_limit_outside_the_documented_bound(db):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    runtime, _, evidence_index = build_runtime()
    await _ingest(db, runtime, authorized, payload=b"A paragraph mentioning datacenter Zurich.\n")
    await EvidenceProjector(runtime).project_once(db, worker_id="worker-a")

    from tests.knowledge_runtime_support import set_evidence_runtime

    set_evidence_runtime(runtime)
    try:
        context = tool_context(user_id=user_id, project_id=workspace_id, project_ids=[workspace_id], db=db)
        tool = KnowledgeSearchTool()
        for limit in (0, -1, MAX_TOOL_RESULT_LIMIT + 1, 500, "8", 4.5, True):
            refused = await tool.execute({"query": "datacenter", "limit": limit}, context)
            assert refused["state"] == "invalid_request", limit
            assert "evidence" not in refused
        for query in (None, 123, True, ["datacenter"], {"term": "datacenter"}):
            refused = await tool.execute({"query": query}, context)
            assert refused["state"] == "invalid_request", query
        accepted = await tool.execute({"query": "datacenter", "limit": MAX_TOOL_RESULT_LIMIT}, context)
        assert accepted["state"] == "ok"
        assert (await tool.execute({"query": "datacenter"}, context))["state"] == "ok"
    finally:
        set_evidence_runtime(None)
