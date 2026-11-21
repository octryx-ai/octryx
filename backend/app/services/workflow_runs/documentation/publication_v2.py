"""Publish & prove Cloud-v2 publication executor: durable intent, governed dispatch and exact read-back.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ...ai_marking import CONFLUENCE_LABEL, facts_to_dict, run_marking_facts, with_storage_marker
from ..platform.dispatch import CLASS_SAFETY, FAILED, ToolOutcome
from ..records import WorkflowRunError, record_event
from .page import recorded_output
from .publication_checks import (
    _approved_body,
    _dispatch_check,
    _head_problem,
    _location,
    _presend_problems,
    _reply_problem,
    _version_message,
)
from .publication_outcome import (
    EVENT_UNVERIFIED,
    STATUS_CREATED,
    STATUS_UPDATED,
    _certify_and_fail,
    _finish_verdict,
    _resume,
    _run_moved,
    _succeeded,
    _verify_confirmed,
)
from .publication_reconciliation import reconcile_attempt as _reconcile_core
from .target import MODE_CREATE

logger = logging.getLogger(__name__)

# --- Publish & prove: publish the approved write intent through Confluence Cloud v2 ---------------------------------
#
# 1. In the run's claimed transaction: the active intent must be approved (a potentially sent one reconciles
#    first), the (b) decision must still be the latest publication decision and bind the exact body and marker,
#    the run must be running (stop) and the pinned settings/connection/instance unchanged (drift). The result is
#    recorded as the intent's ``dispatch_check``.
# 2. One claimed sender: ``approved | never_started_certified -> send_started`` as a compare-and-set, committed
#    together with the pass lease (``external_step``) BEFORE any provider request; no run transaction is held
#    over the network.
# 3. Read-only pre-send checks (space, parent, page base version) and a last stop re-check. A failure there is
#    certified "never started" by this executor (nothing was sent): the only way back to a sendable state.
# 4. The one mutating request. A definite refusal (no answer sent / a 4xx answer: 409 is ``page_changed`` by its
#    status code) is certified never started; anything that may have been applied (timeout, 5xx, a malformed
#    2xx) becomes ``pending_reconcile`` (committed) and is reconciled at once.
# 5. A valid reply is ``sent_confirmed`` (``provider_reply``) after the full storage read-back; the run is then
#    re-claimed (``run_moved_on`` if it moved) and the page recorded.

EVENT_V2_DISPATCH_REFUSED = "documentation_publish_refused"


def v2_transport() -> Any:
    """The provider transport (``None`` = the governed egress). A seam: tests inject a stub transport."""
    return None


async def _before_send(intent: Any) -> None:
    """A seam immediately before the mutating request (crash-injection tests); no behaviour."""
    del intent


async def _label_ai_page(client: Any, page_id: str) -> None:
    """Best effort ``ai-generated`` label on the published page; it never fails or changes the publication."""
    try:
        await client.add_label(page_id, CONFLUENCE_LABEL)
    except Exception:  # noqa: BLE001 - a label is not part of the publication contract
        logger.warning("documentation: could not label page %s %s", page_id, CONFLUENCE_LABEL, exc_info=True)


async def _route_unsendable(db: AsyncSession, run: WorkflowRun, intent: Any, *, transport: Any,
                            worker: str) -> ToolOutcome | None:
    """The answer when the active intent is not sendable (none, potentially sent, or another state)."""
    from ....models.runtime.documentation_publication import (
        INTENT_POTENTIALLY_SENT_STATES,
        INTENT_SENDABLE_STATES,
    )
    from .publication_recovery import reconcile_publication_intent
    from .write_intent import latest_confirmed_intent

    if intent is None:
        done = await latest_confirmed_intent(db, run)
        if done is None:
            return ToolOutcome(FAILED, reason="no approved publication intent on this run", failure_class=CLASS_SAFETY)
        return await _verify_confirmed(db, run, done, transport=transport)
    if intent.state in INTENT_POTENTIALLY_SENT_STATES:
        return await reconcile_publication_intent(db, run, transport=transport, worker_id=worker)
    if intent.state not in INTENT_SENDABLE_STATES:
        return ToolOutcome(FAILED, {"intent_id": intent.id, "state": intent.state},
                           f"the publication intent is {intent.state}, not approved", failure_class=CLASS_SAFETY)
    return None


async def _prepare_send(db: AsyncSession, run: WorkflowRun, intent: Any
                        ) -> ToolOutcome | tuple[str, str, dict[str, Any], Any]:
    """The refusal, or ``(approved body, pass key, dispatch check, served connection)`` for a governed send."""
    from ..external_step import pass_key
    from .confluence_v2 import governed_v2_check
    from .failure_routes import PUBLICATION_STOPPED, TARGET_DRIFT, s1_failure

    body, problem = await _approved_body(db, run, intent)
    if problem:
        return ToolOutcome(FAILED, {"intent_id": intent.id}, problem, failure_class=CLASS_SAFETY)
    key = pass_key(run)
    check, stopped, drift, served = await _dispatch_check(db, run, intent, key)
    if stopped or drift:
        record_event(db, run, EVENT_V2_DISPATCH_REFUSED, node_id=run.current_node_id,
                     detail={"intent_id": intent.id, **check})
        if stopped:
            return s1_failure(PUBLICATION_STOPPED, f"not published: {stopped}", intent_id=intent.id)
        return s1_failure(TARGET_DRIFT, "the publish contract changed after the confirmation: " + "; ".join(drift),
                          intent_id=intent.id, reasons=drift)
    output = recorded_output(run)
    if output is None or output.get("hash") != intent.output_hash:
        return ToolOutcome(FAILED, reason="the recorded documentation changed after publication approval",
                           failure_class=CLASS_SAFETY)
    blocked = await governed_v2_check(db, run, instance=intent.instance, connection_id=intent.connection_id,
                                     space_key=intent.space_key, page_id=intent.page_id, parent_id=intent.parent_id,
                                     title=intent.title, body=body, base_version=intent.base_version)
    if blocked is not None:
        return blocked  # approval_pending/refusal: no claimed sender and no provider request
    return body, key, check, served


async def publish_documentation_v2(db: AsyncSession, run: WorkflowRun, params: dict[str, Any] | None = None, *,
                                   transport: Any = None, worker_id: str | None = None) -> ToolOutcome:
    """Publish the run's approved intent once (see the section comment). The run must be claimed (``lock_run``)."""
    from ..external_step import release_for_external_work
    from .confluence_v2 import CloudV2Client
    from .confluence_v2_errors import V2ProfileRefusalError
    from .failure_routes import NEEDS_CONFIGURATION, s1_failure
    from .write_intent import active_intent, claim_send

    del params
    worker = worker_id or f"publish:{uuid.uuid4().hex[:16]}"
    transport = transport if transport is not None else v2_transport()
    intent = await active_intent(db, run)
    routed = await _route_unsendable(db, run, intent, transport=transport, worker=worker)
    if routed is not None:
        return routed
    prepared = await _prepare_send(db, run, intent)
    if isinstance(prepared, ToolOutcome):
        return prepared
    body, key, check, served = prepared
    # The governed check above sees the approved body; the platform marker is added for the send only.
    marking = await run_marking_facts(db, run)
    check = {**check, "ai_marking": facts_to_dict(marking)}
    if not await claim_send(db, intent, worker=worker, pass_key=key, dispatch_check=check):
        raise WorkflowRunError("action_in_flight", "Another worker holds this publication's send; its result is "
                                                   "recorded when it returns.", 409)
    body = with_storage_marker(body, marking)  # exactly the facts frozen on the claimed intent
    # The claim (send_started) and the pass lease are committed together, before any provider request.
    held = await release_for_external_work(db, run, key=key, facts={})
    try:
        client = CloudV2Client(intent.instance, served.config, transport=transport)
    except V2ProfileRefusalError as refusal:
        return await _certify_and_fail(db, run, intent, held, certified_by=f"{worker}:not_sent",
                                       failure_class=NEEDS_CONFIGURATION, reason=str(refusal))
    async with client:
        sent = await _send_and_prove(db, run, intent, held, client, body=body, worker=worker, marking=marking)
        if isinstance(sent, ToolOutcome):
            return sent
        failure_class, why, reply, head, url = sent
    await _resume(db, run, held)
    if failure_class:
        record_event(db, run, EVENT_UNVERIFIED, node_id=run.current_node_id, detail={
            "intent_id": intent.id, "page_id": reply.id, "version": head.version, "failure_class": failure_class})
        return s1_failure(failure_class, why, intent_id=intent.id, page_id=reply.id, version=head.version)
    return await _succeeded(db, run, intent, head, url=url,
                            status=STATUS_CREATED if intent.operation == MODE_CREATE else STATUS_UPDATED)


async def _presend_gate(db: AsyncSession, run: WorkflowRun, intent: Any, held: Any, client: Any, *,
                        worker: str) -> ToolOutcome | None:
    """Pre-send reads and the last stop re-check; a failure is certified never started (nothing was sent)."""
    from .confluence_v2_errors import V2Error
    from .failure_routes import PUBLICATION_STOPPED, class_of_v2_error

    try:
        problems = await _presend_problems(client, intent)
    except V2Error as error:
        problems = [(class_of_v2_error(error, before_send=True),
                     f"the pre-send check failed ({error.kind}: {str(error)[:160]})")]
    if problems:
        return await _certify_and_fail(db, run, intent, held, certified_by=f"{worker}:not_sent",
                                       failure_class=problems[0][0], reason=problems[0][1],
                                       reasons=[why for _cls, why in problems])
    if await _run_moved(db, run, held):  # a stop during the pre-send reads: nothing has been sent
        from .write_intent import certify_never_started

        await certify_never_started(db, intent, certified_by=f"{worker}:not_sent",
                                    reason="the run moved on before the send", error_class=PUBLICATION_STOPPED)
        await db.commit()
        raise WorkflowRunError("run_moved_on", "The run changed before the publication was sent; nothing was "
                                               "sent.", 409)
    return None


async def _send_failed(db: AsyncSession, run: WorkflowRun, intent: Any, held: Any, client: Any, error: Any, *,
                       body: str, worker: str) -> ToolOutcome:
    """A refused/unsent request is certified never started; a possibly applied one is reconciled at once."""
    from .confluence_v2_errors import SENT_NO, SENT_REFUSED
    from .failure_routes import class_of_v2_error
    from .write_intent import mark_pending_reconcile

    if error.sent in (SENT_NO, SENT_REFUSED):
        failure_class = class_of_v2_error(error, before_send=True)
        state = "provider_refused" if error.sent == SENT_REFUSED else "not_sent"
        return await _certify_and_fail(
            db, run, intent, held, certified_by=f"{worker}:{state}", failure_class=failure_class,
            reason=f"Confluence refused the publication ({error.kind}, HTTP {error.status_code}); nothing "
                   "was applied" if error.sent == SENT_REFUSED else f"the publication was not sent ({error})",
            provider_error=error.to_dict())
    await mark_pending_reconcile(db, intent, reason=f"the send may have been applied: {error}",
                                 error_class=error.kind)
    await db.commit()
    verdict = await _reconcile_core(client, run, intent, body)
    return await _finish_verdict(db, run, intent, verdict, held, client)


async def _send_and_prove(db: AsyncSession, run: WorkflowRun, intent: Any, held: Any, client: Any, *, body: str,
                          worker: str, marking: Any) -> ToolOutcome | tuple[str, str, Any, Any, str]:
    """The one mutating request and its read-back: an answer, or ``(failure class, why, reply, head, url)``."""
    from .confluence_v2_errors import V2Error

    gate = await _presend_gate(db, run, intent, held, client, worker=worker)
    if gate is not None:
        return gate
    await _before_send(intent)
    try:
        if intent.operation == MODE_CREATE:
            reply = await client.create_page(space_id=intent.space_id, parent_id=intent.parent_id,
                                             title=intent.title, storage=body)
        else:
            reply = await client.update_page(page_id=intent.page_id, title=intent.title, storage=body,
                                             version_number=intent.expected_version,
                                             version_message=_version_message(intent))
    except V2Error as error:
        return await _send_failed(db, run, intent, held, client, error, body=body, worker=worker)
    return await _prove_reply(db, run, intent, held, client, reply, body=body, marking=marking)


async def _prove_reply(db: AsyncSession, run: WorkflowRun, intent: Any, held: Any, client: Any, reply: Any, *,
                       body: str, marking: Any) -> ToolOutcome | tuple[str, str, Any, Any, str]:
    """Confirm a reply by the full storage read-back; a reply that proves nothing is reconciled."""
    from .confluence_v2_errors import V2Error
    from .confluence_v2_storage import storage_digest
    from .failure_routes import PROVIDER_UNAVAILABLE, s1_failure
    from .write_intent import mark_pending_reconcile, mark_sent_confirmed

    if why := _reply_problem(intent, reply):
        await mark_pending_reconcile(db, intent, reason=f"the provider reply does not prove the write ({why})",
                                     error_class="malformed", page_id=reply.id)
        await db.commit()
        verdict = await _reconcile_core(client, run, intent, body)
        return await _finish_verdict(db, run, intent, verdict, held, client)
    url = client.page_link(reply)
    try:
        head = await client.get_page(reply.id, storage=True)
    except V2Error as error:
        await mark_sent_confirmed(db, intent, result_kind="provider_reply", page_id=reply.id,
                                  version=reply.version, location=_location(intent, reply.id, url),
                                  storage_digest=None)
        await db.commit()
        await _resume(db, run, held)
        return s1_failure(PROVIDER_UNAVAILABLE, f"the page was written but its read-back failed ({error.kind}); "
                                                "a retry verifies it without writing again", intent_id=intent.id)
    failure_class, why = _head_problem(intent, head, body, reply.storage)
    await mark_sent_confirmed(db, intent, result_kind="provider_reply", page_id=reply.id, version=reply.version,
                              location=_location(intent, reply.id, url),
                              storage_digest=None if failure_class else storage_digest(head.storage))
    await db.commit()
    if not failure_class and marking is not None:
        await _label_ai_page(client, reply.id)
    return failure_class, why, reply, head, url
