"""The asynchronous parse obligation runs through the real projector with a fake parser sandbox, and the adapter refuses an unpinned sandbox and maps its answers."""

from __future__ import annotations

import dataclasses
import json

import httpx
import pytest
from sqlalchemy import func, select

from app.models.project.knowledge_evidence import (
    OUTBOX_OPERATION_PARSE_REVISION,
    OUTBOX_OPERATION_PROJECT_REVISION,
    REVISION_STATE_PROJECTED,
    KnowledgeEvidenceSpan,
    KnowledgeProjectionOutboxEntry,
    KnowledgeSourceRevision,
)
from app.services.knowledge.ingestion.docling_document import parse_document
from app.services.knowledge.ingestion.parser_port import ParserError, ParserIdentity, ParserState, TaskStatus
from app.services.knowledge.ledger.citations import resolve_citations
from app.services.knowledge.projection.projector import EvidenceProjector
from tests.services.knowledge.knowledge_parsed_documents_support import (
    PDF,
    FakeSandbox,
    _document,
    _sandbox,
    _setup,
    _upload,
)


async def _operations(db, revision_id: str) -> dict[str, str]:
    rows = await db.execute(
        select(KnowledgeProjectionOutboxEntry.operation, KnowledgeProjectionOutboxEntry.state).where(
            KnowledgeProjectionOutboxEntry.revision_id == revision_id
        )
    )
    return dict(rows.all())


async def test_a_pdf_is_parsed_in_the_sandbox_then_projected_and_cited_at_its_page(db):
    # the text-layer probe (pending, then done), then the full parse (done)
    sandbox = FakeSandbox(polls=[TaskStatus.PENDING, TaskStatus.SUCCESS, TaskStatus.SUCCESS])
    authorized, user_id, runtime, s3 = await _setup(db, sandbox)
    ingested = await _upload(db, runtime, authorized, user_id)
    assert ingested.span_count == 0 and len(s3.objects) == 1
    assert await _operations(db, ingested.revision_id) == {OUTBOX_OPERATION_PARSE_REVISION: "pending"}

    projector = EvidenceProjector(runtime)
    submitted = await projector.project_once(db, worker_id="test")
    waiting = await projector.project_once(db, worker_id="test", project_id=authorized.project_id)
    # Waiting is not an attempt; the obligation is simply not due yet.
    assert submitted.deferred and sandbox.submitted == [PDF]
    assert waiting is None
    await db.execute(
        KnowledgeProjectionOutboxEntry.__table__.update().values(next_attempt_at=func.now())  # due again
    )
    await db.commit()
    polled = await projector.project_once(db, worker_id="test")
    assert polled.deferred and polled.failure is None
    for _ in ("probe done, OCR decided", "full parse submitted"):
        await db.execute(KnowledgeProjectionOutboxEntry.__table__.update().values(next_attempt_at=func.now()))
        await db.commit()
        step = await projector.project_once(db, worker_id="test")
        assert step.failure is None and not step.applied
    # A born-digital PDF: the probe ran without OCR on the first pages, the full parse without OCR.
    assert sandbox.options == [{"do_ocr": False, "page_range": (1, 20)}, {"do_ocr": False, "page_range": None}]
    await db.execute(KnowledgeProjectionOutboxEntry.__table__.update().values(next_attempt_at=func.now()))
    await db.commit()
    parsed = await projector.project_once(db, worker_id="test")
    assert parsed.applied and parsed.spans_projected == len(parse_document(_document()))
    assert await _operations(db, ingested.revision_id) == {
        OUTBOX_OPERATION_PARSE_REVISION: "applied",
        OUTBOX_OPERATION_PROJECT_REVISION: "pending",
    }

    while await projector.project_once(db, worker_id="test") is not None:
        pass
    state = (
        await db.execute(
            select(KnowledgeSourceRevision.state).where(KnowledgeSourceRevision.id == ingested.revision_id)
        )
    ).scalar_one()
    assert state == REVISION_STATE_PROJECTED
    keys = tuple(
        (
            await db.execute(
                select(KnowledgeEvidenceSpan.evidence_key).where(
                    KnowledgeEvidenceSpan.revision_id == ingested.revision_id
                )
            )
        ).scalars()
    )
    table = next(c for c in (await resolve_citations(db, authorized.project_id, keys)).values() if c.kind == "table")
    assert table.page_start == 4 and table.section_path == ("Order Shipping Protocol", "Message Flow", "Challenge")
    assert table.source_url == "https://docs.example.com/shipping/core.pdf#page=4"
    assert table.citation == "Shipping Core Spec (rev 1, p. 4, § Challenge)"


async def test_a_revision_is_never_parsed_by_a_parser_it_does_not_name(db):
    sandbox = FakeSandbox(polls=[TaskStatus.SUCCESS])
    authorized, user_id, runtime, _ = await _setup(db, sandbox)
    ingested = await _upload(db, runtime, authorized, user_id)
    other = dataclasses.replace(sandbox, identity=ParserIdentity("docling-serve", "1.36.0+p1", "no_network_uds"))

    outcome = await EvidenceProjector(dataclasses.replace(runtime, parser=other)).project_once(db, worker_id="test")

    assert outcome.failure == "parser_contract" and sandbox.submitted == []
    spans = await db.execute(
        select(func.count(KnowledgeEvidenceSpan.id)).where(KnowledgeEvidenceSpan.revision_id == ingested.revision_id)
    )
    assert spans.scalar_one() == 0


async def test_the_adapter_refuses_an_unpinned_sandbox_and_maps_its_answers():
    def unpinned(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/version"
        return httpx.Response(200, json={"docling-serve": "1.36.0"})

    with pytest.raises(ParserError) as raised:
        await _sandbox(unpinned).submit(PDF, "application/pdf")
    assert (raised.value.state, raised.value.reason) == (ParserState.CONTRACT_VIOLATION, "version_mismatch")

    def pinned(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/version":
            return httpx.Response(200, json={"docling-serve": "1.35.0"})
        if request.url.path == "/v1/convert/file/async":
            body = request.content
            # The fixed profile goes along, and the uploader's file name never does.
            assert b'name="pdf_backend"' in body and b"pypdfium2" in body and b'filename="source.pdf"' in body
            return httpx.Response(200, json={"task_id": "0862c324-966a"})
        if request.url.path.endswith("/gone"):
            return httpx.Response(404, json={"detail": "Task not found."})
        if request.url.path.startswith("/v1/status/poll/"):
            return httpx.Response(200, json={"task_status": "started"})
        return httpx.Response(200, content=json.dumps({"status": "failure", "document": {}}).encode())

    parser = _sandbox(pinned)
    assert await parser.submit(PDF, "application/pdf") == "0862c324-966a"
    assert await parser.poll("0862c324-966a") == TaskStatus.PENDING
    assert await parser.poll("gone") == TaskStatus.LOST
    with pytest.raises(ParserError) as refused:
        await parser.result("0862c324-966a")
    assert refused.value.state == ParserState.REFUSED
