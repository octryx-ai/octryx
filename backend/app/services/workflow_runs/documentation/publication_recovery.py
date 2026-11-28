"""Publish & prove recovery: reconcile a potentially sent publication intent before any new write."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ..platform.dispatch import CLASS_INVALID, CLASS_SAFETY, FAILED, ToolOutcome
from ..records import WorkflowRunError
from .publication_checks import _approved_body, _sent_body
from .publication_outcome import _finish_verdict, _verify_confirmed
from .publication_reconciliation import reconcile_attempt as _reconcile_core


async def _reconcile_target(db: AsyncSession, run: WorkflowRun, intent: Any) -> ToolOutcome | Any:
    from .confluence_v2 import governed_v2_check
    from .failure_routes import RECONCILE_INCOMPLETE, s1_failure
    from .target import ConnectionUnavailableError, served_confluence

    try:
        served = await served_confluence(db, run, intent.space_key)
    except ConnectionUnavailableError as error:
        return s1_failure(RECONCILE_INCOMPLETE, f"the pinned connection is unavailable ({error.code}); the earlier "
                                                "attempt stays pending", intent_id=intent.id)
    if (served.connection_id, served.instance) != (intent.connection_id, intent.instance):
        return s1_failure(RECONCILE_INCOMPLETE, "the space is no longer served by the pinned connection and "
                                                "instance; the earlier attempt can only be reconciled there",
                          intent_id=intent.id)
    blocked = await governed_v2_check(db, run, instance=intent.instance, connection_id=intent.connection_id,
                                     space_key=intent.space_key, page_id=intent.result_page_id or intent.page_id,
                                     parent_id=intent.parent_id)
    if blocked is not None:
        return blocked
    return served


async def reconcile_publication_intent(db: AsyncSession, run: WorkflowRun, params: dict[str, Any] | None = None, *,
                                       transport: Any = None, worker_id: str | None = None) -> ToolOutcome:
    # Nothing here writes to Confluence or makes an intent sendable again; only the executor's certification does.
    from ....models.runtime.documentation_publication import INTENT_POTENTIALLY_SENT_STATES, INTENT_SEND_STARTED
    from ..external_step import pass_key, release_for_external_work
    from .confluence_v2 import CloudV2Client
    from .confluence_v2_errors import V2ProfileRefusalError
    from .publication_v2 import v2_transport
    from .write_intent import active_intent, latest_confirmed_intent, lease_expired, mark_pending_reconcile

    del params
    worker = worker_id or f"reconcile:{uuid.uuid4().hex[:16]}"
    transport = transport if transport is not None else v2_transport()
    intent = await active_intent(db, run)
    if intent is None:
        done = await latest_confirmed_intent(db, run)
        if done is None:
            return ToolOutcome(FAILED, reason="no publication intent to reconcile", failure_class=CLASS_INVALID)
        return await _verify_confirmed(db, run, done, transport=transport)
    if intent.state not in INTENT_POTENTIALLY_SENT_STATES:
        return ToolOutcome(FAILED, {"intent_id": intent.id, "state": intent.state},
                           f"the publication intent is {intent.state}: nothing was sent, nothing to reconcile",
                           failure_class=CLASS_INVALID)
    if intent.state == INTENT_SEND_STARTED:
        if intent.claimed_by != worker and not lease_expired(intent):
            raise WorkflowRunError("action_in_flight", "Another worker is sending this publication right now; its "
                                                       "result is recorded when it returns.", 409)
        await mark_pending_reconcile(db, intent, reason="recovered: the send started without a recorded outcome "
                                                        f"(sender {intent.claimed_by})", error_class="send_started")
    body, problem = await _approved_body(db, run, intent)
    if problem:
        return ToolOutcome(FAILED, {"intent_id": intent.id}, problem, failure_class=CLASS_SAFETY)
    body = _sent_body(intent, body)
    served = await _reconcile_target(db, run, intent)
    if isinstance(served, ToolOutcome):
        return served
    held = await release_for_external_work(db, run, key=pass_key(run), facts={})
    try:
        client = CloudV2Client(intent.instance, served.config, transport=transport)
    except V2ProfileRefusalError as refusal:
        verdict: dict[str, Any] = {"kind": "incomplete", "reason": str(refusal)}
        return await _finish_verdict(db, run, intent, verdict, held, None)
    async with client:
        verdict = await _reconcile_core(client, run, intent, body)
        return await _finish_verdict(db, run, intent, verdict, held, client)
