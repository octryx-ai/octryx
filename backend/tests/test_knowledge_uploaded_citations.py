"""Knowledge tools cite an uploaded source's exact revision through the governed original route.

- the same-Workspace link the tools emit opens the exact bytes for an authorized reader and is the same 404
  for an outsider (the link grants nothing);
- a bound Workspace's passage gets no manufactured link; a source's own public link is kept;
- a tombstoned or foreign revision yields no read link;
- compaction keeps the citation identity;
- the answer-evidence guard recognizes exactly that route and nothing else.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.main import app
from app.services.answer_evidence.check import check_answer_evidence
from app.services.answer_evidence.evidence import collect_turn_evidence
from app.services.answer_evidence.knowledge_original_links import knowledge_original_path, knowledge_original_url
from app.services.answer_evidence.urls import normalize_url, urls_in_text
from app.services.auth import get_current_user
from app.services.knowledge.runtime import set_evidence_runtime
from app.tools.knowledge_evidence.read import KnowledgeReadTool
from app.tools.knowledge_evidence.result_compaction import compact_knowledge_search
from app.tools.knowledge_evidence.search import KnowledgeSearchTool
from app.tools.knowledge_evidence.source_links import presented_citation, read_source_url
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import (
    fetch_user,
    new_workspace_id,
    seed_member,
    seed_outsider,
    seed_workspace,
    tool_context,
)

BASE = "/api/v1/workspaces"
TEXT = b"The Zurich datacenter hosts the primary cluster.\n\nFailover runs from Geneva.\n"
WS = "785b4554-bfbc-41f6-9f39-d408868134b2"
SRC = "0f0e5a52-7d1c-4a49-9f1e-1b2c3d4e5f60"
REV = "6a5b4c3d-2e1f-4a0b-8c9d-0e1f2a3b4c5d"


@pytest.fixture
def evidence_runtime():
    runtime, s3, evidence_index = build_runtime()
    set_evidence_runtime(runtime)
    try:
        yield runtime, s3, evidence_index
    finally:
        set_evidence_runtime(None)


@pytest.fixture
def as_user(db):
    def _install(user):
        app.dependency_overrides[get_current_user] = lambda: user

    yield _install
    app.dependency_overrides.pop(get_current_user, None)


async def _uploaded_workspace(client, db, as_user, evidence_index):
    workspace_id = await seed_workspace(db)
    owner_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    as_user(await fetch_user(db, owner_id))
    created = await client.post(
        f"{BASE}/{workspace_id}/knowledge/sources",
        files={"file": ("ignored.txt", TEXT, "text/plain")},
        data={"source_key": "runbook", "display_title": "Zurich runbook"},
    )
    assert created.status_code == 201
    assert (await client.post(f"{BASE}/{workspace_id}/knowledge/projection/run")).json()["applied"] is True
    return workspace_id, owner_id, created.json()


async def test_the_emitted_link_opens_the_exact_revision_and_grants_nothing(client, db, as_user, evidence_runtime):
    _, _, evidence_index = evidence_runtime
    workspace_id, owner_id, created = await _uploaded_workspace(client, db, as_user, evidence_index)
    context = tool_context(user_id=owner_id, project_id=workspace_id, project_ids=[workspace_id], db=db)

    result = await KnowledgeSearchTool().execute({"query": "datacenter"}, context)
    hit = compact_knowledge_search(result)["evidence"][0]
    expected = f"{BASE}/{workspace_id}/knowledge/sources/{created['source_id']}/revisions/{created['revision_id']}/original"
    assert hit["source_url"] == expected
    assert hit["cite_as"] == f"[Zurich runbook]({expected})" and hit["revision_id"] == created["revision_id"]
    read = await KnowledgeReadTool().execute({"evidence_key": hit["evidence_key"]}, context)
    assert read["source_url"] == expected

    opened = await client.get(hit["source_url"])
    assert opened.status_code == 200 and opened.content == TEXT
    as_user(await fetch_user(db, await seed_outsider(db)))
    assert (await client.get(hit["source_url"])).status_code == 404, "the link itself grants no access"


async def test_a_tombstoned_or_foreign_revision_has_no_read_link(client, db, as_user, evidence_runtime):
    _, _, evidence_index = evidence_runtime
    workspace_id, _, created = await _uploaded_workspace(client, db, as_user, evidence_index)
    key = created["revision_id"].replace("-", "") + ":1"
    assert await read_source_url(
        db, source_url=None, workspace_id=workspace_id, primary_workspace_id=workspace_id, evidence_key=key
    ) is not None
    other = new_workspace_id()
    assert await read_source_url(
        db, source_url=None, workspace_id=other, primary_workspace_id=other, evidence_key=key
    ) is None, "the revision belongs to another Workspace"
    assert (await client.delete(f"{BASE}/{workspace_id}/knowledge/sources/{created['source_id']}")).status_code == 200
    assert await read_source_url(
        db, source_url=None, workspace_id=workspace_id, primary_workspace_id=workspace_id, evidence_key=key
    ) is None, "a removed source is not linked"
    for malformed in ("not-a-key", "zz:1", None):
        assert await read_source_url(
            db, source_url=None, workspace_id=workspace_id, primary_workspace_id=workspace_id, evidence_key=malformed
        ) is None


def _citation(**overrides):
    values = {"source_url": None, "source_id": SRC, "revision_id": REV, "source_title": "Runbook", "section_path": ()}
    return SimpleNamespace(**{**values, **overrides})


def test_bound_passages_get_no_manufactured_link_and_public_links_are_kept():
    own = presented_citation(_citation(), workspace_id=WS, primary_workspace_id=WS)
    assert own["source_url"] == f"{BASE}/{WS}/knowledge/sources/{SRC}/revisions/{REV}/original"
    bound = presented_citation(_citation(), workspace_id=new_workspace_id(), primary_workspace_id=WS)
    assert bound == {"source_url": None, "cite_as": "Runbook (no link)"}
    public = "https://docs.example.test/runbook"
    for workspace_id in (WS, new_workspace_id()):
        kept = presented_citation(_citation(source_url=public), workspace_id=workspace_id, primary_workspace_id=WS)
        assert kept == {"source_url": public, "cite_as": f"[Runbook]({public})"}
    no_identity = presented_citation(_citation(source_id="", revision_id=""), workspace_id=WS, primary_workspace_id=WS)
    assert no_identity["source_url"] is None
    sectioned = presented_citation(_citation(section_path=("Failover",)), workspace_id=WS, primary_workspace_id=WS)
    assert sectioned["cite_as"].startswith("[Runbook § Failover](")


def test_compaction_keeps_the_citation_identity():
    link = f"{BASE}/{WS}/knowledge/sources/{SRC}/revisions/{REV}/original"
    result = {"state": "ok", "evidence": [{
        "evidence_key": "k:1", "text": "x", "source_url": link, "cite_as": f"[Runbook]({link})", "revision_id": REV,
        "pages": [2, 2], "section": "Failover", "similarity": 0.4,
    }]}
    passage = compact_knowledge_search(result)["evidence"][0]
    assert (passage["source_url"], passage["cite_as"], passage["revision_id"], passage["pages"]) == (
        link, f"[Runbook]({link})", REV, [2, 2])
    assert "similarity" not in passage


@pytest.mark.parametrize("url", [
    f"{BASE}/{WS}/knowledge/sources/{SRC}/revisions/{REV}/original",
    f"{BASE}/{WS}/knowledge/sources/{SRC.replace('-', '')}/revisions/{REV.replace('-', '')}/original",
])
def test_the_exact_original_route_is_recognized(url):
    assert knowledge_original_url(url) == url == normalize_url(url)
    assert urls_in_text(f"See [Runbook]({url}).") == [url]


@pytest.mark.parametrize("url", [
    f"{BASE}/{WS.upper()}/knowledge/sources/{SRC}/revisions/{REV}/original",
    f"{BASE}/{WS}/knowledge/sources/{SRC}/revisions/{REV}/original/",
    f"{BASE}/{WS}/knowledge/sources/{SRC}/revisions/{REV}/original#page=2",
    f"{BASE}/{WS}/knowledge/sources/{SRC}/revisions/{REV}/text",
    f"{BASE}/{WS}/knowledge/sources/{SRC}/revisions/{REV}",
    f"{BASE}/{WS}/knowledge/sources/{SRC}/revisions/{REV}/original\\x",
    f"{BASE}/{WS}/knowledge/sources/not-a-uuid/revisions/{REV}/original",
    f"https://evil.example{BASE}/{WS}/knowledge/sources/{SRC}/revisions/{REV}/original",
    f"/api/v2/workspaces/{WS}/knowledge/sources/{SRC}/revisions/{REV}/original",
    f"{BASE}/{WS}/web-search",
])
def test_anything_else_under_the_api_is_not_a_source(url):
    assert knowledge_original_url(url) is None
    if url.startswith("/"):
        assert normalize_url(url) is None


def test_the_builder_refuses_inexact_identities():
    assert knowledge_original_path(WS, SRC, REV) is not None
    for args in ((WS, "", REV), (WS, SRC, None), ("Workspace A", SRC, REV), (WS, "../x", REV), (WS, SRC, REV + "?a=1")):
        assert knowledge_original_path(*args) is None


def test_public_and_repository_citations_still_work_next_to_originals():
    original = f"{BASE}/{WS}/knowledge/sources/{SRC}/revisions/{REV}/original"
    evidence = collect_turn_evidence([
        {"tool_name": "knowledge_search", "result": {"state": "ok", "evidence": [
            {"source_url": original, "source_title": "Runbook"},
            {"source_url": "https://docs.example.test/page#intro", "source_title": "Docs"},
        ]}},
    ])
    answer = f"Failover runs from Geneva ([Runbook]({original})).\n\nSee the docs ([Docs](https://docs.example.test/page))."
    checked = check_answer_evidence(answer, evidence)
    assert checked.satisfied and checked.uncited_count == 0 and not checked.invented_urls
    assert checked.evidence_url_count == 2, "the uploaded original and the public page are both sources"
