"""Publish & prove outcomes: record the proven page, certify a never-started send, finish a reconciliation."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ..platform.dispatch import CLASS_SAFETY, FAILED, SUCCEEDED, ToolOutcome
from ..records import record_event
from .publication_checks import _approved_body, _head_problem, _location, _sent_body
from .target import PROVIDER

EVENT_UNVERIFIED = "documentation_publish_unverified"
STATUS_CREATED, STATUS_UPDATED, STATUS_RECONCILED = "created", "updated", "reconciled"


async def _run_moved(db: AsyncSession, run: WorkflowRun, held: Any) -> bool:
    from ..external_step import _moved

    await db.refresh(run)
    return bool(_moved(run, held, {}))


async def _record_v2(db: AsyncSession, run: WorkflowRun, intent: Any, page: Any, *, url: str, status: str,
                     digest: str) -> dict[str, Any]:
    from .confluence_v2 import TRANSPORT_NAME

    recorded = {"provider": PROVIDER, "transport": TRANSPORT_NAME, "space_key": intent.space_key,
                "space_id": intent.space_id, "parent_id": intent.parent_id, "page_id": page.id, "title": page.title,
                "url": url, "version": page.version, "status": status, "connection_id": intent.connection_id,
                "instance": intent.instance, "output_hash": intent.output_hash,
                "storage_sha256": digest.removeprefix("sha256:"), "storage_digest": digest,
                "intent_id": intent.id, "operation_id": intent.operation_id, "marker": intent.marker,
                "result_kind": intent.result_kind}
    from ....models import AuditLog

    audited = (await db.execute(select(AuditLog.id).where(
        AuditLog.action == "s1.documentation.published", AuditLog.resource_id == intent.id))).first()
    if audited is None:
        db.add(AuditLog(user_id=run.requested_by, action="s1.documentation.published",
                        resource_type="documentation_write_intent", resource_id=intent.id,
                        project_id=run.project_id,
                        details={"run_id": run.id, "operation_id": intent.operation_id,
                                 "page_id": page.id, "version": page.version, "storage_digest": digest,
                                 "connection_id": intent.connection_id, "instance": intent.instance,
                                 "result_kind": intent.result_kind}))

    from .publish import _record

    await _record(db, run, recorded)
    return recorded


async def _succeeded(db: AsyncSession, run: WorkflowRun, intent: Any, page: Any, *, url: str, status: str
                     ) -> ToolOutcome:
    digest = str(intent.result_storage_digest or "")
    recorded = await _record_v2(db, run, intent, page, url=url, status=status, digest=digest)
    return ToolOutcome(SUCCEEDED, {"page_id": page.id, "version": page.version,
                                   "location": dict(intent.result_location or {}), "storage_digest": digest,
                                   "status": status, "intent_id": intent.id, "operation_id": intent.operation_id,
                                   "result_kind": intent.result_kind, "page": recorded})


async def _resume(db: AsyncSession, run: WorkflowRun, held: Any) -> None:
    from ..external_step import resume_after_external_work

    await resume_after_external_work(db, run, held, {})


async def _certify_and_fail(db: AsyncSession, run: WorkflowRun, intent: Any, held: Any, *, certified_by: str,
                            failure_class: str, reason: str, **detail: Any) -> ToolOutcome:
    from .failure_routes import S1_ROUTES, s1_failure
    from .write_intent import certify_never_started

    await certify_never_started(db, intent, certified_by=certified_by, reason=reason, error_class=failure_class)
    await db.commit()  # the certification is durable on its own, whatever happens to the run
    await _resume(db, run, held)
    if failure_class in S1_ROUTES:
        return s1_failure(failure_class, reason, intent_id=intent.id, **detail)
    return ToolOutcome(FAILED, {"intent_id": intent.id, **detail}, reason[:500], failure_class=failure_class)


async def _finish_verdict(db: AsyncSession, run: WorkflowRun, intent: Any, verdict: dict[str, Any], held: Any,
                          client: Any) -> ToolOutcome:
    from .confluence_v2_storage import storage_digest
    from .failure_routes import PAGE_CHANGED, PUBLISH_UNVERIFIED, RECONCILE_INCOMPLETE, s1_failure
    from .write_intent import mark_sent_confirmed, transition

    detail = {key: value for key, value in verdict.items() if key not in ("kind", "page", "head", "reason")}
    if verdict["kind"] != "adopt":
        failure_class = RECONCILE_INCOMPLETE if verdict["kind"] == "incomplete" else PUBLISH_UNVERIFIED
        await transition(db, intent, str(intent.state), last_error_class=failure_class,
                         last_error=str(verdict["reason"])[:2000])
        await db.commit()
        await _resume(db, run, held)
        record_event(db, run, EVENT_UNVERIFIED, node_id=run.current_node_id, detail={
            "intent_id": intent.id, "failure_class": failure_class, "reason": verdict["reason"], **detail})
        return s1_failure(failure_class, str(verdict["reason"]), intent_id=intent.id, **detail)
    page, head = verdict["page"], verdict["head"]
    url = client.page_link(head)
    await mark_sent_confirmed(db, intent, result_kind=str(verdict["result_kind"]), page_id=page.id,
                              version=intent.expected_version, location=_location(intent, page.id, url),
                              storage_digest=storage_digest(page.storage))
    await db.commit()
    await _resume(db, run, held)
    if head.version != intent.expected_version:
        return s1_failure(PAGE_CHANGED, f"the approved write was adopted at version {intent.expected_version}, but "
                                        f"page {page.id} has since moved on to version {head.version}",
                          intent_id=intent.id, page_id=page.id, version=intent.expected_version,
                          head_version=head.version)
    return await _succeeded(db, run, intent, page, url=url, status=STATUS_RECONCILED)


async def _verify_confirmed(db: AsyncSession, run: WorkflowRun, intent: Any, *, transport: Any) -> ToolOutcome:
    # A sent-confirmed intent is never sent again.
    from ..external_step import pass_key, release_for_external_work
    from .confluence_v2 import CloudV2Client
    from .confluence_v2_errors import V2Error, V2ProfileRefusalError
    from .confluence_v2_storage import storage_digest
    from .failure_routes import PROVIDER_UNAVAILABLE, TARGET_DRIFT, s1_failure
    from .target import ConnectionUnavailableError, served_confluence
    from .write_intent import transition

    body, problem = await _approved_body(db, run, intent)
    if problem:
        return ToolOutcome(FAILED, {"intent_id": intent.id}, problem, failure_class=CLASS_SAFETY)
    body = _sent_body(intent, body)
    try:
        served = await served_confluence(db, run, intent.space_key)
    except ConnectionUnavailableError as error:
        return s1_failure(TARGET_DRIFT, f"the pinned connection is unavailable ({error.code})")
    if (served.connection_id, served.instance) != (intent.connection_id, intent.instance):
        return s1_failure(TARGET_DRIFT, "the space is no longer served by the pinned connection and instance")
    from .confluence_v2 import governed_v2_check

    blocked = await governed_v2_check(db, run, instance=intent.instance, connection_id=intent.connection_id,
                                     space_key=intent.space_key, page_id=intent.result_page_id or intent.page_id,
                                     parent_id=intent.parent_id)
    if blocked is not None:
        return blocked
    held = await release_for_external_work(db, run, key=pass_key(run), facts={})
    try:
        async with CloudV2Client(intent.instance, served.config, transport=transport) as client:
            head = await client.get_page(str(intent.result_page_id), storage=True)
            failure_class, why = _head_problem(intent, head, body)
            url = client.page_link(head)
    except (V2Error, V2ProfileRefusalError) as error:
        await _resume(db, run, held)
        return s1_failure(PROVIDER_UNAVAILABLE, f"the read-back of the published page failed ({error}); nothing is "
                                                "written again", intent_id=intent.id)
    if not failure_class and not intent.result_storage_digest:
        await transition(db, intent, str(intent.state), result_storage_digest=storage_digest(head.storage),
                         result_location=_location(intent, head.id, url))
        await db.commit()
    await _resume(db, run, held)
    if failure_class:
        return s1_failure(failure_class, why, intent_id=intent.id, page_id=head.id, version=head.version)
    return await _succeeded(db, run, intent, head, url=url, status=STATUS_RECONCILED)
