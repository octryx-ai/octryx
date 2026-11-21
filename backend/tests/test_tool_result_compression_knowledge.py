"""Confluence search and page compression and evidence contracts for hard-capped knowledge results."""

import uuid

import pytest
from sqlalchemy import select

from app.agent.loops.outcome._loop_evidence_contracts import (
    build_incomplete_evidence_contract_reminder,
    critical_incomplete_evidence_contracts,
)
from app.models import Session, ToolResultCompressionLog, ToolResultCompressor, User
from app.services.tool_result_compression import (
    compress_tool_result_for_model,
    ensure_default_tool_result_compressors,
)


@pytest.mark.asyncio
async def test_confluence_search_and_page_are_compressed(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    search = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="search_confluence",
        result={
            "query": "report-builder",
            "cql": 'text ~ "report-builder"',
            "total": 18,
            "results": [
                {
                    "id": str(100 + i),
                    "title": f"report-builder page {i}",
                    "space_key": "INFRA",
                    "version": i,
                    "url": f"https://example.test/{i}",
                    "updated_by": {"name": "alice", "display_name": "Alice Example"},
                    "updated_when": "2026-06-05T13:30:52.083+02:00",
                    "child_count": 1,
                    "child_listing_complete": True,
                    "children": [
                        {
                            "id": f"child-{i}",
                            "title": f"child page {i}",
                            "version": 1,
                            "updated_by": {"name": "alice", "display_name": "Alice Example"},
                            "updated_when": "2026-06-05T13:31:52.083+02:00",
                        }
                    ],
                    "content": "x" * 1000,
                }
                for i in range(12)
            ],
        },
    )
    assert search["result_count"] == 12
    assert len(search["results"]) == 8
    assert search["results"][0]["title"] == "report-builder page 0"
    assert search["results"][0]["updated_by"]["display_name"] == "Alice Example"
    assert search["results"][0]["child_count"] == 1
    assert search["results"][0]["children"][0]["title"] == "child page 0"
    assert search["evidence_contract"]["status"] == "passed"
    assert search["evidence_contract"]["required_paths"] == ["query", "total", "result_count", "results"]

    page = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="get_confluence_page",
        result={
            "id": "100001",
            "title": "Report Builder guide",
            "space_key": "INFRA",
            "version": 5,
            "url": "https://example.test/page",
            "content": (
                "<h1>Report Builder</h1>"
                "<p>Python utility that builds weekly order reports from the shop's exports.</p>"
                "<h2>Contents</h2><p>Main runner, config, and report templates.</p>"
                "<h2>Integration</h2><p>Runs once a week after the nightly export.</p>"
                + "<p>"
                + ("extra text " * 1000)
                + "</p>"
            ),
        },
    )
    assert page["title"] == "Report Builder guide"
    assert page["headings"][:2] == ["Report Builder", "Contents"]
    assert "Python utility" in page["excerpt"]
    assert page["text_length"] > len(page["excerpt"])
    assert page["evidence_contract"]["status"] == "passed"
    assert page["evidence_contract"]["missing_paths"] == []

    logs = (
        (
            await db.execute(
                select(ToolResultCompressionLog).where(
                    ToolResultCompressionLog.session_id == session.id,
                    ToolResultCompressionLog.tool_name.in_(["search_confluence", "get_confluence_page"]),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(logs) == 2
    assert all(log.compressed_tokens < log.original_tokens for log in logs)


@pytest.mark.asyncio
async def test_evidence_contract_marks_hard_capped_knowledge_result_incomplete(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await ensure_default_tool_result_compressors(db)
    row = (
        await db.execute(select(ToolResultCompressor).where(ToolResultCompressor.tool_name == "get_confluence_page"))
    ).scalar_one()
    row.is_active = False
    await db.commit()

    page = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="get_confluence_page",
        result={
            "id": "100001",
            "title": "Report Builder guide",
            "space_key": "INFRA",
            "version": 5,
            "url": "https://example.test/page",
            "headings": ["Report Builder"],
            "excerpt": "Existing excerpt",
            "text_length": 120000,
            "content": "Report Builder operational evidence. " * 20000,
        },
    )

    contract = page["evidence_contract"]
    assert contract["status"] == "failed"
    assert contract["hard_capped"] is True
    assert contract["evidence_state"] == "incomplete_compact_evidence"
    incomplete = critical_incomplete_evidence_contracts(
        [
            {
                "artifact_id": "artifact-1",
                "tool_name": "get_confluence_page",
                "compact_result": page,
            }
        ]
    )
    assert incomplete == [
        {
            "artifact_id": "artifact-1",
            "tool_name": "get_confluence_page",
            "missing_paths": [],
            "hard_capped": True,
            "evidence_state": "incomplete_compact_evidence",
        }
    ]
    reminder = build_incomplete_evidence_contract_reminder(incomplete)
    assert "load_tool_artifact" in reminder
    assert "artifact-1" in reminder
