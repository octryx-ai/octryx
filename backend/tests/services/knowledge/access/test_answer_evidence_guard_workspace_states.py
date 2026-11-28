"""Knowledge evidence reports closed empty-Workspace states: no sources yet, pending, or needs configuration."""

from __future__ import annotations

import pytest

from app.api.routes.knowledge._knowledge_evidence_http import STATUS_BY_STATE
from app.main import app
from app.services.auth import get_current_user
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from app.services.knowledge.ledger.errors import EvidenceLedgerState
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.mcp_governed_knowledge import McpCaller, run_governed_mcp_tool
from app.tools.knowledge_evidence._scope import STATE_MESSAGES
from app.tools.knowledge_evidence.search import KnowledgeSearchTool
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace, tool_context
from tests.knowledge_runtime_support import set_evidence_runtime

# --- empty Workspace states --------------------------------------------------------------------------


@pytest.fixture
def evidence_runtime():
    runtime, _, evidence_index = build_runtime()
    set_evidence_runtime(runtime)
    try:
        yield runtime, evidence_index
    finally:
        set_evidence_runtime(None)


async def _workspace(db, runtime, evidence_index, *, ingest: bool, project: bool) -> tuple[str, str]:
    workspace_id = await seed_workspace(db)
    author_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    if ingest:
        authorized = await authorize_workspace(db, current_user=await fetch_user(db, author_id), workspace_id=workspace_id)
        await ingest_text_source(
            db,
            runtime=runtime,
            authorized=authorized,
            source_key="failover-runbook",
            display_title="Failover Runbook",
            declared_media_type="text/markdown",
            data=b"# Drill\n\nThe failover drill runs from Geneva every quarter.\n",
            created_by=author_id,
            source_url="https://confluence.example.test/wiki/Failover",
        )
        if project:
            await EvidenceProjector(runtime).project_once(db, worker_id="test")
    return workspace_id, author_id


async def _search(db, workspace_id: str, user_id: str) -> dict:
    context = tool_context(user_id=user_id, project_id=workspace_id, project_ids=[workspace_id], db=db)
    return await KnowledgeSearchTool().execute({"query": "failover drill"}, context)


@pytest.mark.asyncio
async def test_a_never_ingested_workspace_has_no_sources_yet(client, db, evidence_runtime) -> None:
    workspace_id, user_id = await _workspace(db, *evidence_runtime, ingest=False, project=False)

    result = await _search(db, workspace_id, user_id)
    assert result == {"error": STATE_MESSAGES["no_sources"], "state": "no_sources"}
    assert "Add a source" in result["error"]

    caller = McpCaller(user_id=user_id, grant_id="g1", scopes=("knowledge:read",), client_name="claude-code", workspace_header=workspace_id)
    mcp = await run_governed_mcp_tool(db, caller=caller, tool_name="knowledge_search", arguments={"query": "failover"})
    assert mcp["state"] == "no_sources"

    user = await fetch_user(db, user_id)
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        response = await client.post(f"/api/v1/workspaces/{workspace_id}/knowledge/search", json={"query_text": "x"})
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert (response.status_code, response.json()["detail"]) == STATUS_BY_STATE[EvidenceLedgerState.NO_SOURCES]


@pytest.mark.asyncio
async def test_sources_without_a_current_projection_are_pending(db, evidence_runtime) -> None:
    workspace_id, user_id = await _workspace(db, *evidence_runtime, ingest=True, project=False)
    result = await _search(db, workspace_id, user_id)
    assert result == {"error": STATE_MESSAGES["projection_pending"], "state": "projection_pending"}


@pytest.mark.asyncio
async def test_a_projected_workspace_answers_and_storage_misconfiguration_stays_needs_configuration(
    db, evidence_runtime
) -> None:
    workspace_id, user_id = await _workspace(db, *evidence_runtime, ingest=True, project=True)
    assert (await _search(db, workspace_id, user_id))["state"] == "ok"

    set_evidence_runtime(None)
    from app.services.knowledge import runtime as runtime_module

    runtime_module._UNCONFIGURED = True
    try:
        refused = await _search(db, workspace_id, user_id)
    finally:
        runtime_module._UNCONFIGURED = False
    assert refused["state"] == "needs_configuration" and "administrator" in refused["error"]
    assert STATUS_BY_STATE[EvidenceLedgerState.NEEDS_CONFIGURATION][0] == 503
