"""Structured facts stay inside the knowledge_search expansion budget, a failing structured store never fails a search, and status counts and reports are guarded."""

from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy import event

from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.retrieval import graph_expansion
from app.services.knowledge.structured import config_report
from app.services.knowledge.structured.config_report import handbook_vs_reality
from app.services.knowledge.structured.status import structured_status
from app.tools.knowledge_evidence.search import KnowledgeSearchTool
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, tool_context
from tests.test_structured_graph_report import _workspace
from tests.test_structured_graph_surfacing import _full

# --- Search -----------------------------------------------------------------------------------------


async def _search(db, user, authorized) -> dict:
    context = tool_context(user_id=user.id, project_id=authorized.project_id, project_ids=[authorized.project_id],
                           db=db)
    return await KnowledgeSearchTool().execute({"query": "Empty quotes from the pricing service"}, context)


def _structured_kinds(found: dict) -> set[str]:
    return {item["kind"] for item in found["facts"]["facts"]} & {"CAUSED_BY", "ASSIGNED_TO_GROUP", "AFFECTS_SERVICE"}


async def test_a_raising_structured_store_never_fails_knowledge_search(db, monkeypatch, caplog):
    user, authorized = await _full(db)
    assert _structured_kinds(await _search(db, user, authorized))

    async def raising(*args, **kwargs):
        raise RuntimeError("structured store down")

    monkeypatch.setattr(graph_expansion, "structured_hit_facts", raising)
    with caplog.at_level(logging.WARNING, logger=graph_expansion.__name__):
        found = await _search(db, user, authorized)
    assert found["state"] == "ok" and found["evidence"]
    assert not _structured_kinds(found)
    assert "Structured graph expansion failed" in caplog.text and "RuntimeError" in caplog.text
    assert "structured store down" not in caplog.text


async def test_structured_facts_stay_inside_the_expansion_budget(db, monkeypatch, caplog):
    user, authorized = await _full(db)

    async def slow(*args, **kwargs):
        await asyncio.sleep(5)
        return ()

    monkeypatch.setattr(graph_expansion, "structured_hit_facts", slow)
    monkeypatch.setattr(graph_expansion, "EXPANSION_BUDGET_SECONDS", 0.2)
    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger=graph_expansion.__name__):
        found = await _search(db, user, authorized)
    assert time.monotonic() - started < 3
    assert found["state"] == "ok" and found["evidence"] and not _structured_kinds(found)
    assert "budget spent" in caplog.text


# --- Counts, caps and re-redaction ----------------------------------------------------------------


async def test_status_counts_are_shown_to_authors_only(db):
    user, authorized, _, _ = await _workspace(db)
    admin = await structured_status(db, authorized=authorized)
    assert admin["counts_visible"] is True and admin["layers"]["configuration"]["revisions"] >= 1
    assert admin["builds"][0]["report"]["layers"]

    member_id = await seed_member(db, workspace_id=authorized.project_id, role="member")
    member = await authorize_workspace(db, current_user=await fetch_user(db, member_id),
                                       workspace_id=authorized.project_id)
    status = await structured_status(db, authorized=member)
    assert status["counts_visible"] is False and status["layers"] is None
    assert status["builds"] and all(build["report"] is None for build in status["builds"])
    assert status["builds"][0]["state"] == "completed"


async def test_the_report_reads_a_capped_edge_set(db, monkeypatch):
    _, authorized, _, _ = await _workspace(db)
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = db.bind.sync_engine if hasattr(db.bind, "sync_engine") else db.bind
    event.listen(engine, "before_cursor_execute", record)
    try:
        whole = await handbook_vs_reality(db, authorized=authorized)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    edge_reads = [sql for sql in statements if "FROM knowledge_structured_edges" in sql]
    # The cap is part of every edge read, before any row is loaded.
    assert edge_reads and all("LIMIT" in sql for sql in edge_reads)
    assert whole["edges_capped"] is False and max(whole["counts"].values()) > 1
    monkeypatch.setattr(config_report, "MAX_EDGES_PER_TYPE", 1)
    capped = await handbook_vs_reality(db, authorized=authorized)
    assert capped["edges_capped"] is True and capped["truncated"] is True
    # Every count of findings is bounded by the edges read; only the key total of a section is larger.
    assert max(count for name, count in capped["counts"].items() if name != "unknown_section_settings") <= 1
