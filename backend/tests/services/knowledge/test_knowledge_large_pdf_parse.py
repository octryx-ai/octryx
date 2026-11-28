"""Large PDFs through the parser sandbox: a configurable parse wait that keeps polling an expired task
(``docling-serve`` cannot cancel one), and OCR decided per PDF by a cheap probe."""

from __future__ import annotations

import dataclasses
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select, update

from app.models.project.knowledge_evidence import KnowledgeProjectionOutboxEntry, KnowledgeSourceRevision
from app.models.project.knowledge_parsing import KnowledgeParseTask
from app.services.knowledge.ingestion.ocr_choice import (
    OcrSetting,
    decided_version,
    needs_ocr,
    ocr_setting,
    registered_version,
    text_layer_share,
)
from app.services.knowledge.ingestion.parser_port import ParserError, ParserState, TaskStatus
from app.services.knowledge.projection.parse_step import MAX_PARSE_WAIT_ENV, max_parse_wait
from app.services.knowledge.projection.projector import EvidenceProjector
from app.time_utils import utc_now
from tests.services.knowledge.knowledge_parsed_documents_support import (
    PDF,
    FakeSandbox,
    _document,
    _sandbox,
    _setup,
    _upload,
)


def test_the_parse_wait_comes_from_the_environment_within_bounds():
    assert max_parse_wait({}) == timedelta(minutes=45)
    assert max_parse_wait({MAX_PARSE_WAIT_ENV: " 120 "}) == timedelta(minutes=120)
    assert max_parse_wait({MAX_PARSE_WAIT_ENV: "5"}) == timedelta(minutes=5)
    assert max_parse_wait({MAX_PARSE_WAIT_ENV: "240"}) == timedelta(minutes=240)
    for invalid in ("4", "241", "90.5", "-10", "ninety"):
        with pytest.raises(ParserError) as raised:
            max_parse_wait({MAX_PARSE_WAIT_ENV: invalid})
        assert (raised.value.state, raised.value.reason) == (ParserState.NEEDS_CONFIGURATION, "max_parse_wait_invalid")


async def _age_task(db, minutes: int) -> None:
    await db.execute(update(KnowledgeParseTask).values(submitted_at=utc_now() - timedelta(minutes=minutes)))
    await db.execute(update(KnowledgeProjectionOutboxEntry).values(next_attempt_at=func.now()))
    await db.commit()


async def _decided(db) -> None:
    await db.execute(update(KnowledgeSourceRevision).values(parser_version="1.35.0+p1.do_ocr=false"))
    await db.commit()


async def _due(db) -> None:
    await db.execute(update(KnowledgeProjectionOutboxEntry).values(next_attempt_at=func.now()))
    await db.commit()


async def test_a_timed_out_task_is_kept_and_polled_never_submitted_twice(db, monkeypatch):
    monkeypatch.delenv(MAX_PARSE_WAIT_ENV, raising=False)
    sandbox = FakeSandbox(polls=[TaskStatus.PENDING, TaskStatus.PENDING, TaskStatus.SUCCESS])
    authorized, user_id, runtime, _ = await _setup(db, sandbox)
    await _upload(db, runtime, authorized, user_id)
    await _decided(db)
    projector = EvidenceProjector(runtime)
    await projector.project_once(db, worker_id="test")
    assert sandbox.submitted == [PDF]

    await _age_task(db, 50)  # past the default 45 minutes, still running
    timed_out = await projector.project_once(db, worker_id="test")
    assert timed_out.failure is not None and not timed_out.applied
    tasks = (await db.execute(select(KnowledgeParseTask.task_ref))).scalars().all()
    assert tasks == ["task-1"], "the running task is kept, not forgotten"

    await _due(db)
    again = await projector.project_once(db, worker_id="test")
    assert again.failure is not None and sandbox.submitted == [PDF], "the retry polls, it never resubmits"

    await _due(db)
    finished = await projector.project_once(db, worker_id="test")
    assert finished.applied and finished.spans_projected > 0, "a late result is still written"
    assert sandbox.submitted == [PDF]


async def test_a_longer_configured_wait_lets_a_long_parse_keep_waiting(db, monkeypatch):
    monkeypatch.setenv(MAX_PARSE_WAIT_ENV, "120")
    sandbox = FakeSandbox(polls=[TaskStatus.PENDING, TaskStatus.SUCCESS])
    authorized, user_id, runtime, _ = await _setup(db, sandbox)
    await _upload(db, runtime, authorized, user_id)
    await _decided(db)
    projector = EvidenceProjector(runtime)
    await projector.project_once(db, worker_id="test")
    await _age_task(db, 75)  # a ~950-page manual
    waiting = await projector.project_once(db, worker_id="test")
    assert waiting.failure is None and not waiting.applied
    await _due(db)
    assert (await projector.project_once(db, worker_id="test")).applied
    assert sandbox.submitted == [PDF]


def _probe(pages: dict[int, str | None]) -> dict:
    texts = [{"label": "text", "text": text, "prov": [{"page_no": page}]} for page, text in pages.items() if text]
    pictures = [{"label": "picture", "prov": [{"page_no": page}]} for page, text in pages.items() if text is None]
    return {"texts": texts, "pictures": pictures, "tables": []}


def test_the_ocr_decision_follows_the_text_layer_share_of_the_probe():
    line = "A born-digital page carries its own text layer."
    assert not needs_ocr(_probe({page: line for page in range(1, 21)}))
    assert needs_ocr(_probe({page: None for page in range(1, 21)})), "a scanned PDF keeps OCR"
    nine_of_ten = {page: line for page in range(1, 10)} | {10: None}
    assert text_layer_share(_probe(nine_of_ten)) == 0.9 and not needs_ocr(_probe(nine_of_ten))
    eight_of_ten = {page: line for page in range(1, 9)} | {9: None, 10: None}
    assert needs_ocr(_probe(eight_of_ten))
    assert needs_ocr(_probe({1: line, 2: "p. 2", 3: "x"})), "a page number alone is not a text layer"
    blank_pages = _probe({page: line for page in range(1, 10)})  # a blank page has no items at all: not sampled
    assert not needs_ocr(blank_pages)
    assert needs_ocr({}) and needs_ocr({"texts": "junk"}), "no usable sample keeps OCR on"


def test_the_ocr_setting_is_part_of_the_recorded_parser_version():
    assert registered_version("1.35.0+p1", "application/pdf") == "1.35.0+p1.do_ocr=auto"
    docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert registered_version("1.35.0+p1", docx) == "1.35.0+p1"
    assert decided_version("1.35.0+p1", False) == "1.35.0+p1.do_ocr=false"
    assert decided_version("1.35.0+p1", True) == "1.35.0+p1.do_ocr=true"
    assert ocr_setting("1.35.0+p1", "1.35.0+p1") == OcrSetting.ON, "a revision registered without a choice (not a PDF) keeps the parser's default"
    assert ocr_setting("1.35.0+p1.do_ocr=false", "1.35.0+p1") == OcrSetting.OFF
    assert ocr_setting("1.35.0+p1.do_ocr=auto", "1.35.0+p1") == OcrSetting.AUTO
    assert ocr_setting("1.35.0+p1.do_ocr=false", "1.36.0+p1") is None
    assert ocr_setting("1.35.0+p1.do_ocr=maybe", "1.35.0+p1") is None
    assert len("1234.1234.1234+p1.do_ocr=false") <= 30, "fits the revision's parser_version column"


@dataclasses.dataclass
class ScannedSandbox(FakeSandbox):
    async def result(self, task_ref: str) -> dict:
        return _probe({page: None for page in range(1, 21)}) if task_ref == "task-1" else _document()


async def _drive(db, projector, runs: int) -> None:
    for _ in range(runs):
        await _due(db)
        outcome = await projector.project_once(db, worker_id="test")
        assert outcome is not None and outcome.failure is None


@pytest.mark.parametrize(("sandbox_type", "ocr", "recorded"), [
    (FakeSandbox, False, "1.35.0+p1.do_ocr=false"),
    (ScannedSandbox, True, "1.35.0+p1.do_ocr=true"),
])
async def test_a_pdf_is_probed_then_parsed_with_the_decided_ocr(db, sandbox_type, ocr, recorded):
    sandbox = sandbox_type(polls=[TaskStatus.SUCCESS, TaskStatus.SUCCESS])
    authorized, user_id, runtime, _ = await _setup(db, sandbox)
    ingested = await _upload(db, runtime, authorized, user_id)
    version = select(KnowledgeSourceRevision.parser_version).where(KnowledgeSourceRevision.id == ingested.revision_id)
    assert (await db.execute(version)).scalar_one() == "1.35.0+p1.do_ocr=auto"
    projector = EvidenceProjector(runtime)
    await projector.project_once(db, worker_id="test")  # submits the probe
    await _drive(db, projector, 2)  # probe done: decided; full parse submitted
    assert (await db.execute(version)).scalar_one() == recorded
    assert sandbox.options == [{"do_ocr": False, "page_range": (1, 20)}, {"do_ocr": ocr, "page_range": None}]
    await _due(db)
    assert (await projector.project_once(db, worker_id="test")).applied


async def test_the_adapter_sends_the_ocr_and_probe_options_per_request():
    forms: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/version":
            return httpx.Response(200, json={"docling-serve": "1.35.0"})
        forms.append(request.content)
        return httpx.Response(200, json={"task_id": f"t-{len(forms)}"})

    parser = _sandbox(handler)
    await parser.submit(PDF, "application/pdf", do_ocr=False, page_range=(1, 20))
    await parser.submit(PDF, "application/pdf", do_ocr=False)
    await parser.submit(PDF, "application/pdf")
    probe, born_digital, default = forms

    def field(body: bytes, name: str) -> list[bytes]:
        marker = f'name="{name}"\r\n\r\n'.encode()
        return [part.split(b"\r\n", 1)[0] for part in body.split(marker)[1:]]

    assert field(probe, "do_ocr") == [b"false"] and field(probe, "page_range") == [b"1", b"20"]
    assert field(probe, "do_table_structure") == [b"false"]
    assert field(born_digital, "do_ocr") == [b"false"] and field(born_digital, "page_range") == []
    assert field(born_digital, "table_mode") == [b"accurate"] and field(born_digital, "do_table_structure") == []
    assert field(default, "do_ocr") == [b"true"]
    for bad in ((0, 5), (5, 1), ("1", "5")):
        with pytest.raises(ParserError) as raised:
            await parser.submit(PDF, "application/pdf", page_range=bad)
        assert raised.value.state == ParserState.CONTRACT_VIOLATION
