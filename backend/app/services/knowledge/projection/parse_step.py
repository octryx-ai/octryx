"""One bounded run of a ``parse_revision`` obligation.

A sandboxed revision is registered without spans. Its parse is asynchronous in the Docling
sandbox, so the obligation is advanced over several short runs, never one long one:

1. **Submit.** The first run reads the original from object storage (digest-verified), submits it,
   and records the sandbox task (``knowledge_parse_tasks``). The obligation then waits.
2. **Poll.** Later runs ask the sandbox where the task is. Waiting is not a failed attempt. A task
   still running after the configured wait (:func:`max_parse_wait`), that the sandbox no longer
   knows, or that the sandbox refused, is a failure with a fixed token and follows the bounded retry.
   ``docling-serve`` cannot cancel a task, so a timed-out task is *kept*: the retry polls the same
   task (and writes its result once it finishes) instead of submitting a second full parse of the
   same revision. Only a lost or failed task is forgotten and submitted afresh.
3. **Write.** The run that finds the task done maps the document to located spans and adds, in the
   caller's transaction, the spans, their locators, the revision's span count, and the projection
   obligation. The caller's ``mark_applied`` commits all of it together, or nothing on a lost lease.

The parser identity the revision was registered with must be the one configured now; a different
parser is a contract failure, so a revision's spans always come from the parser it names.

A PDF registered with an undecided OCR setting (``ocr_choice.py``) first runs the cheap
text-layer probe through the same submit/poll cycle; its result completes the revision's parser
version (``.do_ocr=false`` or ``.do_ocr=true``) and the full parse is submitted with that setting.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.ledger.obligations import ensure_projection

from ....models.project.knowledge_evidence import (
    KnowledgeEvidenceSource,
    KnowledgeEvidenceSpan,
    KnowledgeSourceRevision,
)
from ....models.project.knowledge_parsing import KnowledgeParseTask, KnowledgeSpanLocator
from ....time_utils import utc_now
from ..identity.workspace import WorkspaceId
from ..ingestion.docling_document import parse_document
from ..ingestion.ocr_choice import PROBE_PAGES, OcrSetting, decided_version, needs_ocr, ocr_setting
from ..ingestion.parser_port import ParserError, ParserState, TaskStatus
from ..ingestion.spans import derive_evidence_key, derive_located_citation
from ..ledger.errors import EvidenceLedgerError, EvidenceRecordNotFoundError
from ..objects import KnowledgeObjectError
from ..objects.source_object import SourceObjectRef
from ..runtime import EvidenceRuntime
from .outbox_lease import ClaimedProjection

PARSE_POLL_SECONDS = 10
MAX_PARSE_WAIT_ENV = "OCTRYX_KNOWLEDGE_MAX_PARSE_WAIT_MINUTES"
DEFAULT_MAX_PARSE_WAIT_MINUTES = 45
MAX_PARSE_WAIT_BOUNDS = (5, 240)


def max_parse_wait(environ: Mapping[str, str] = os.environ) -> timedelta:
    """How long one sandbox task may run (``OCTRYX_KNOWLEDGE_MAX_PARSE_WAIT_MINUTES``, 5–240, default 45).

    A ~950-page manual takes 55–75 minutes in the local sandbox, so the wait is the operator's choice;
    a value that is not a whole number in bounds is ``needs_configuration``, never a silent default.
    """
    raw = (environ.get(MAX_PARSE_WAIT_ENV) or "").strip()
    if not raw:
        return timedelta(minutes=DEFAULT_MAX_PARSE_WAIT_MINUTES)
    low, high = MAX_PARSE_WAIT_BOUNDS
    if not raw.isdigit() or not low <= int(raw) <= high:
        raise ParserError(ParserState.NEEDS_CONFIGURATION, "max_parse_wait_invalid")
    return timedelta(minutes=int(raw))


async def _revision(db: AsyncSession, claim: ClaimedProjection):
    row = (
        await db.execute(
            select(
                KnowledgeSourceRevision.media_type,
                KnowledgeSourceRevision.object_bucket,
                KnowledgeSourceRevision.object_key,
                KnowledgeSourceRevision.object_version_id,
                KnowledgeSourceRevision.content_sha256,
                KnowledgeSourceRevision.parser_name,
                KnowledgeSourceRevision.parser_version,
                KnowledgeSourceRevision.parser_sandbox,
                KnowledgeSourceRevision.revision_ordinal,
                KnowledgeEvidenceSource.display_title,
            )
            .join(KnowledgeEvidenceSource, KnowledgeEvidenceSource.id == KnowledgeSourceRevision.source_id)
            .where(
                KnowledgeSourceRevision.id == claim.revision_id,
                KnowledgeSourceRevision.project_id == claim.project_id,
            )
        )
    ).first()
    if row is None:
        raise EvidenceRecordNotFoundError()
    return row


async def _task(db: AsyncSession, claim: ClaimedProjection) -> KnowledgeParseTask | None:
    return (
        await db.execute(
            select(KnowledgeParseTask).where(
                KnowledgeParseTask.revision_id == claim.revision_id,
                KnowledgeParseTask.project_id == claim.project_id,
            )
        )
    ).scalar_one_or_none()


async def _forget_task(db: AsyncSession, claim: ClaimedProjection) -> None:
    await db.execute(
        delete(KnowledgeParseTask).where(
            KnowledgeParseTask.revision_id == claim.revision_id,
            KnowledgeParseTask.project_id == claim.project_id,
        )
    )
    await db.commit()


async def _submit(
    db: AsyncSession, runtime: EvidenceRuntime, workspace: WorkspaceId, claim, revision, ocr: OcrSetting
) -> None:
    ref = SourceObjectRef(bucket=revision[1], key=revision[2], version_id=revision[3], content_sha256=revision[4])
    try:
        data = await runtime.object_store.get_verified(workspace, ref)
    except KnowledgeObjectError:
        raise ParserError(ParserState.UNAVAILABLE, "original_unreadable") from None
    if ocr == OcrSetting.AUTO:  # the text-layer probe: OCR off, the first pages only
        task_ref = await runtime.parser.submit(data, revision[0], do_ocr=False, page_range=(1, PROBE_PAGES))
    else:
        task_ref = await runtime.parser.submit(data, revision[0], do_ocr=ocr == OcrSetting.ON)
    db.add(KnowledgeParseTask(revision_id=claim.revision_id, project_id=claim.project_id, task_ref=task_ref))
    await db.commit()


async def parse_revision_step(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    workspace: WorkspaceId,
    claim: ClaimedProjection,
    hold_lease: Callable[[], Awaitable[bool]],
) -> int | None:
    """Advance one parse. Returns the span count once written, ``None`` while it waits."""
    parser = runtime.parser
    if parser is None:
        raise ParserError(ParserState.NEEDS_CONFIGURATION, runtime.parser_unavailable_reason)
    revision = await _revision(db, claim)
    identity = parser.identity
    ocr = ocr_setting(revision[6], identity.version)
    if (revision[5], revision[7]) != (identity.name, identity.sandbox) or ocr is None:
        raise ParserError(ParserState.CONTRACT_VIOLATION, "parser_identity")

    task = await _task(db, claim)
    if task is None:
        await _submit(db, runtime, workspace, claim, revision, ocr)
        return None
    wait = max_parse_wait()
    status = await parser.poll(task.task_ref)
    if status == TaskStatus.PENDING:
        if utc_now() - task.submitted_at > wait:
            # Still running, and the sandbox cannot cancel it: the task is kept, so the retry polls it
            # again instead of piling a second full parse of this revision onto the sandbox.
            raise ParserError(ParserState.UNAVAILABLE, "timeout")
        return None
    if status != TaskStatus.SUCCESS:
        # Lost and failed tasks are both submitted afresh by the next attempt.
        await _forget_task(db, claim)
        raise ParserError(
            ParserState.REFUSED if status == TaskStatus.FAILURE else ParserState.UNAVAILABLE, status.value
        )

    document = await parser.result(task.task_ref)
    if ocr == OcrSetting.AUTO:
        if await hold_lease():
            await _decide_ocr(db, claim, identity.version, document)
        return None  # the next run submits the full parse with the decided setting
    try:
        located = parse_document(document)
    except EvidenceLedgerError:
        # An empty document, or more spans than a revision may hold: this document, not the sandbox.
        await _forget_task(db, claim)
        raise ParserError(ParserState.REFUSED, "document_not_citable") from None
    if not await hold_lease():
        return None
    await _write_spans(db, claim, revision, located)
    return len(located)


async def _write_spans(db: AsyncSession, claim: ClaimedProjection, revision, located) -> None:
    """The spans, the revision's span count and the projection obligation; the parse task is done."""
    _add_spans(db, claim, revision, located)
    await db.execute(
        update(KnowledgeSourceRevision)
        .where(KnowledgeSourceRevision.id == claim.revision_id, KnowledgeSourceRevision.project_id == claim.project_id)
        .values(span_count=len(located))
    )
    await db.execute(
        delete(KnowledgeParseTask).where(
            KnowledgeParseTask.revision_id == claim.revision_id, KnowledgeParseTask.project_id == claim.project_id
        )
    )
    await ensure_projection(db, claim.project_id, claim.revision_id)


async def _decide_ocr(db: AsyncSession, claim: ClaimedProjection, parser_version: str, probe: dict) -> None:
    """Complete the revision's parser identity with the probe's OCR decision; the probe task is done."""
    await db.execute(
        update(KnowledgeSourceRevision)
        .where(KnowledgeSourceRevision.id == claim.revision_id, KnowledgeSourceRevision.project_id == claim.project_id)
        .values(parser_version=decided_version(parser_version, needs_ocr(probe)))
    )
    await _forget_task(db, claim)  # commits both


def _add_spans(db: AsyncSession, claim: ClaimedProjection, revision, located) -> None:
    title, ordinal = revision[9], revision[8]
    for item in located:
        span = item.span
        db.add(
            KnowledgeEvidenceSpan(
                id=str(uuid.uuid4()),
                revision_id=claim.revision_id,
                project_id=claim.project_id,
                span_ordinal=span.span_ordinal,
                evidence_key=derive_evidence_key(claim.revision_id, span.span_ordinal),
                char_start=span.char_start,
                char_end=span.char_end,
                text=span.text,
                citation=derive_located_citation(
                    title,
                    ordinal,
                    page_start=item.page_start,
                    page_end=item.page_end,
                    section=item.section_path[-1] if item.section_path else None,
                ),
            )
        )
        db.add(
            KnowledgeSpanLocator(
                revision_id=claim.revision_id,
                span_ordinal=span.span_ordinal,
                project_id=claim.project_id,
                kind=item.kind,
                page_start=item.page_start,
                page_end=item.page_end,
                section_path=list(item.section_path),
            )
        )


__all__ = ["MAX_PARSE_WAIT_ENV", "PARSE_POLL_SECONDS", "max_parse_wait", "parse_revision_step"]
