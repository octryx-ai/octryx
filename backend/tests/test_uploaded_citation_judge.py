"""Independent acceptance: uploaded evidence must remain openable in chat."""

from urllib.parse import urlsplit

import pytest

from app.services.answer_evidence.check import check_answer_evidence
from app.services.answer_evidence.evidence import collect_turn_evidence
from app.services.answer_evidence.urls import normalize_url
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.runtime import set_evidence_runtime
from app.tools.knowledge_evidence.read import KnowledgeReadTool
from app.tools.knowledge_evidence.result_compaction import compact_knowledge_search
from app.tools.knowledge_evidence.search import KnowledgeSearchTool
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace, tool_context

WORKSPACE = "785b4554-bfbc-41f6-9f39-d408868134b2"
SOURCE = "11111111111141118111111111111111"
REVISION = "22222222222242228222222222222222"
ORIGINAL = f"/api/v1/workspaces/{WORKSPACE}/knowledge/sources/{SOURCE}/revisions/{REVISION}/original"


def evidence_with_url(url=ORIGINAL):
    return collect_turn_evidence([
        {"tool_name": "knowledge_search", "result": {
            "state": "ok", "evidence": [{"source_url": url, "source_title": "Runbook (revision 1)"}],
        }},
    ])


def test_uploaded_original_counts_as_evidence_and_requires_a_citation():
    evidence = evidence_with_url()
    assert evidence.evidence_bearing, "A governed uploaded original must not become unsourced"
    assert not check_answer_evidence("The drill runs on Tuesday.", evidence).satisfied
    answer = f"The drill runs on Tuesday ([Runbook]({ORIGINAL}))."
    checked = check_answer_evidence(answer, evidence)
    assert checked.satisfied and checked.cited_count == 1


def test_a_different_revision_is_not_a_source_of_this_turn():
    evidence = evidence_with_url()
    other = ORIGINAL.replace(REVISION, "33333333333343338333333333333333")
    checked = check_answer_evidence(f"The drill runs on Tuesday ([Runbook]({other})).", evidence)
    assert not checked.satisfied
    assert checked.invented_urls == (other,)


@pytest.mark.parametrize("url", [
    "/api/v1/workspaces/invalid/knowledge/sources/x/revisions/y/original",
    ORIGINAL + "?access_token=synthetic-placeholder",
    ORIGINAL + "?redirect=https://example.test",
    ORIGINAL.replace("/original", "/delete"),
    ORIGINAL.replace("/sources/", "/sources/../"),
    ORIGINAL.replace(SOURCE, "%2e%2e"),
    "//example.test" + ORIGINAL,
    "/api/v1/admin/users",
])
def test_original_recognition_does_not_allow_arbitrary_internal_routes(url):
    assert normalize_url(url) is None


@pytest.mark.parametrize("tool_name", ["knowledge_search", "knowledge_read"])
async def test_actual_uploaded_source_tool_result_has_an_exact_revision_link(db, tool_name):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    runtime, _, evidence_index = build_runtime()
    uploaded = await ingest_text_source(
        db, runtime=runtime, authorized=authorized, source_key="judge-uploaded-runbook",
        display_title="Uploaded runbook", declared_media_type="text/plain",
        data=b"The failover drill runs every Tuesday.", created_by=user_id,
    )
    projector = EvidenceProjector(runtime)
    while await projector.project_once(db, worker_id="judge") is not None:
        pass
    context = tool_context(user_id=user_id, project_id=workspace_id, project_ids=[workspace_id], db=db)
    set_evidence_runtime(runtime)
    try:
        result = await KnowledgeSearchTool().execute({"query": "failover drill"}, context)
        assert result["state"] == "ok" and result["evidence"]
        if tool_name == "knowledge_search":
            hit = compact_knowledge_search(result)["evidence"][0]
        else:
            hit = await KnowledgeReadTool().execute({"evidence_key": result["evidence"][0]["evidence_key"]}, context)
        link = hit.get("source_url")
        assert isinstance(link, str) and link, "The model needs an openable uploaded-source citation"
        expected = (
            f"/api/v1/workspaces/{workspace_id}/knowledge/sources/{uploaded.source_id}"
            f"/revisions/{uploaded.revision_id}/original"
        )
        assert urlsplit(link).path == expected
        assert not urlsplit(link).netloc and not urlsplit(link).query
        assert "failover drill" in hit["text"]
    finally:
        set_evidence_runtime(None)
