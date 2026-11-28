"""The documentation write intent: reserve, approve, claim, certify and finish one approved write."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import DocumentationWriteIntent, WorkflowRun, WorkflowRunDecision
from ....models.runtime.documentation_publication import (
    DOCUMENTATION_SLOT,
    INTENT_ACTIVE_STATES,
    INTENT_APPROVED,
    INTENT_NEVER_STARTED_CERTIFIED,
    INTENT_PENDING_RECONCILE,
    INTENT_POTENTIALLY_SENT_STATES,
    INTENT_RESERVED,
    INTENT_SEND_STARTED,
    INTENT_SENDABLE_STATES,
    INTENT_SENT_CONFIRMED,
    INTENT_SUPERSEDED,
    MARKER_PREFIX,
    intent_marker,
    intent_transition_allowed,
)
from ....time_utils import utc_now
from ....tools._confluence_storage import normalize_storage_content
from ...project.service import get_project_config
from ..graph import CONFIRMED
from ..platform.dispatch import ToolOutcome
from ..records import WorkflowRunError, record_event
from .decision_authority import publication_decision_problem
from .failure_routes import NEEDS_CONFIGURATION, s1_failure
from .page import documentation_settings, page_title, recorded_output

PUBLICATION_SUBJECT = "publication"
#: A live sender owns a ``send_started`` intent this long; after it a crashed send is recovered by reconciliation.
SEND_LEASE_SECONDS = 5 * 60
EVENT_RESERVED = "documentation_intent_reserved"
EVENT_APPROVED = "documentation_intent_approved"
_PINNED = ("connection_id", "instance", "space_id", "space_key", "parent_id", "page_id", "title", "operation",
           "base_version")
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
MARKER_PATTERN = re.compile(
    rf"(?<![0-9A-Za-z_-]){re.escape(MARKER_PREFIX)}:({_UUID}):([0-9a-f]{{32}})(?![0-9A-Za-z_-])")


class PublicationIntentError(WorkflowRunError):
    def __init__(self, code: str, message: str, *, blockers: list[str] | None = None) -> None:
        super().__init__(code, message, 409)
        self.blockers = list(blockers or [message])


def publication_body_hash(body: str) -> str:
    return "sha256:" + hashlib.sha256(normalize_storage_content(body).encode("utf-8")).hexdigest()


def markers_in(storage: str | None) -> set[tuple[str, str]]:
    # A longer token never matches.
    return {(match.group(1), match.group(2)) for match in MARKER_PATTERN.finditer(str(storage or ""))}


def confirmed_binding_problem(intent: DocumentationWriteIntent, payload: dict[str, Any], *,
                              output_hash: str, body_hash: str, workspace_id: str | None) -> str:
    # The decision must bind the whole server-owned intent, not only its body.
    target = payload.get("target")
    expected = {key: getattr(intent, key) for key in _PINNED if key != "title"}
    expected.update(operation_id=intent.operation_id, marker=intent.marker, expected_version=intent.expected_version,
                    workspace_id=workspace_id)
    if not isinstance(target, dict):
        return "the confirmed publication has no pinned target"
    for key, value in expected.items():
        if key not in target or target[key] != value or (isinstance(value, int) and type(target[key]) is not int):
            return f"the confirmed target does not bind {key}"
    if payload.get("title") != intent.title or payload.get("output_hash") != output_hash:
        return "the confirmed title or output does not bind this intent"
    body = payload.get("body")
    if not isinstance(body, str) or publication_body_hash(body) != body_hash:
        return "the confirmed body does not bind its hash"
    if (intent.run_id, intent.operation_id) not in markers_in(body):
        return "the confirmed body does not carry this intent's marker"
    return ""



async def active_intent(db: AsyncSession, run: WorkflowRun, slot: str = DOCUMENTATION_SLOT
                        ) -> DocumentationWriteIntent | None:
    row = (await db.execute(select(DocumentationWriteIntent).where(
        DocumentationWriteIntent.run_id == run.id, DocumentationWriteIntent.slot == slot,
        DocumentationWriteIntent.state.in_(INTENT_ACTIVE_STATES)))).scalar_one_or_none()
    if row is not None:
        await db.refresh(row)
    return row


async def latest_confirmed_intent(db: AsyncSession, run: WorkflowRun, slot: str = DOCUMENTATION_SLOT
                                  ) -> DocumentationWriteIntent | None:
    row = (await db.execute(select(DocumentationWriteIntent).where(
        DocumentationWriteIntent.run_id == run.id, DocumentationWriteIntent.slot == slot,
        DocumentationWriteIntent.state == INTENT_SENT_CONFIRMED)
        .order_by(DocumentationWriteIntent.sent_confirmed_at.desc()).limit(1))).scalar_one_or_none()
    if row is not None:
        await db.refresh(row)
    return row


async def latest_publication_decision(db: AsyncSession, run: WorkflowRun) -> WorkflowRunDecision | None:
    return (await db.execute(
        select(WorkflowRunDecision).where(WorkflowRunDecision.run_id == run.id,
                                          WorkflowRunDecision.subject == PUBLICATION_SUBJECT)
        .order_by(WorkflowRunDecision.created_at.desc()).limit(1))).scalar_one_or_none()



class IntentMovedError(Exception):
    pass


async def transition(db: AsyncSession, intent: DocumentationWriteIntent, target: str, **values: Any) -> None:
    current, seen = str(intent.state), int(intent.state_version or 0)
    if target != current and not intent_transition_allowed(current, target):
        raise ValueError(f"intent transition {current} -> {target} is not allowed")
    result = await db.execute(
        update(DocumentationWriteIntent)
        .where(DocumentationWriteIntent.id == intent.id, DocumentationWriteIntent.state == current,
               DocumentationWriteIntent.state_version == seen)
        .values(state=target, state_version=seen + 1, updated_at=utc_now(), **values)
        .execution_options(synchronize_session=False))
    await db.refresh(intent)
    if result.rowcount != 1:
        raise IntentMovedError(f"intent {intent.id} moved ({current}@{seen} -> {intent.state}@{intent.state_version})")


async def claim_send(db: AsyncSession, intent: DocumentationWriteIntent, *, worker: str, pass_key: str,
                     dispatch_check: dict[str, Any]) -> bool:
    if intent.state not in INTENT_SENDABLE_STATES:
        return False
    now = utc_now()
    try:
        await transition(db, intent, INTENT_SEND_STARTED, claimed_by=worker, claimed_at=now, send_started_at=now,
                         dispatch_pass_key=pass_key, dispatch_check=dispatch_check, last_error_class=None,
                         last_error=None)
    except IntentMovedError:
        return False
    return True


async def certify_never_started(db: AsyncSession, intent: DocumentationWriteIntent, *, certified_by: str,
                                reason: str, error_class: str | None = None) -> None:
    await transition(db, intent, INTENT_NEVER_STARTED_CERTIFIED, certified_by=certified_by[:128],
                     certified_at=utc_now(), claimed_by=None, claimed_at=None, last_error_class=error_class,
                     last_error=reason[:2000])


async def mark_pending_reconcile(db: AsyncSession, intent: DocumentationWriteIntent, *, reason: str,
                                 error_class: str | None = None, page_id: str | None = None,
                                 version: int | None = None) -> None:
    values: dict[str, Any] = {"pending_reconcile_at": utc_now(), "last_error_class": error_class,
                              "last_error": reason[:2000]}
    if page_id:
        values.update(result_page_id=page_id, result_version=version)
    await transition(db, intent, INTENT_PENDING_RECONCILE, **values)


async def mark_sent_confirmed(db: AsyncSession, intent: DocumentationWriteIntent, *, result_kind: str, page_id: str,
                              version: int, location: dict[str, Any], storage_digest: str | None) -> None:
    await transition(db, intent, INTENT_SENT_CONFIRMED, result_kind=result_kind, result_page_id=page_id,
                     result_version=version, result_location=location, result_storage_digest=storage_digest,
                     sent_confirmed_at=utc_now(), last_error_class=None, last_error=None)


def lease_expired(intent: DocumentationWriteIntent) -> bool:
    started = intent.claimed_at or intent.send_started_at
    if started is None:
        return True
    return utc_now().replace(tzinfo=None) - started.replace(tzinfo=None) >= timedelta(seconds=SEND_LEASE_SECONDS)



def _same_target(intent: DocumentationWriteIntent, pinned: dict[str, Any]) -> bool:
    return all((getattr(intent, key) or None) == (pinned.get(key) or None) for key in _PINNED)


async def reserve_publication_intent(db: AsyncSession, run: WorkflowRun, *, transport: Any = None,
                                     node_id: str | None = None) -> DocumentationWriteIntent:
    from ..external_step import pass_key
    from .target import resolve_v2_target

    output = recorded_output(run)
    if output is None:
        raise PublicationIntentError("documentation_missing", "No feature documentation was recorded in this run.")
    settings = documentation_settings(await get_project_config(run.project_id, db))
    if settings is None:
        raise PublicationIntentError(NEEDS_CONFIGURATION, "The Workspace names no documentation space "
                                                          "(feature_documentation.confluence_space_key).")
    active = await active_intent(db, run)
    if active is not None and active.state in INTENT_POTENTIALLY_SENT_STATES:
        raise PublicationIntentError("reconcile_first", f"The earlier publication attempt {active.operation_id} may "
                                                        "have reached Confluence; it is reconciled before any new "
                                                        "publication is prepared.")
    title = page_title(run, dict(output.get("record") or {}))
    target = await resolve_v2_target(db, run, settings, title=title, transport=transport)
    if target.blockers:
        raise PublicationIntentError(target.blocker_code or "target_blocked", target.blockers[0],
                                     blockers=target.blockers)
    pinned = target.pinned()
    if active is not None:
        if _same_target(active, pinned):
            return active  # a retried pass (any pass key) keeps the intent and its marker
        await transition(db, active, INTENT_SUPERSEDED, superseded_at=utc_now())
    operation_id = uuid.uuid4().hex
    intent = DocumentationWriteIntent(
        operation_id=operation_id, marker=intent_marker(run.id, operation_id), run_id=run.id,
        slot=DOCUMENTATION_SLOT, node_id=str(node_id or run.current_node_id or ""),
        reserved_pass_key=pass_key(run, node_id), connection_id=target.connection_id, instance=target.instance,
        space_id=target.space_id, space_key=target.space_key, parent_id=target.parent_id,
        page_id=target.page_id, title=title, operation=target.operation, base_version=target.base_version,
        expected_version=1 if target.operation == "create" else int(target.base_version or 0) + 1,
        state=INTENT_RESERVED, state_version=0)
    try:
        async with db.begin_nested():
            db.add(intent)
    except IntegrityError:
        # Another reservation won the slot concurrently: the same target is the same intent.
        winner = await active_intent(db, run)
        if winner is not None and winner.state not in INTENT_POTENTIALLY_SENT_STATES and _same_target(winner,
                                                                                                       pinned):
            return winner
        raise PublicationIntentError("intent_busy", "Another publication intent was reserved for this run at the "
                                                    "same time; try again.") from None
    if superseded := (active.id if active is not None else None):
        await db.execute(update(DocumentationWriteIntent).where(DocumentationWriteIntent.id == superseded)
                         .values(superseded_by_id=intent.id).execution_options(synchronize_session=False))
    record_event(db, run, EVENT_RESERVED, node_id=intent.node_id, detail={
        "intent_id": intent.id, "operation_id": operation_id, "operation": intent.operation,
        "space_key": intent.space_key, "parent_id": intent.parent_id, "page_id": intent.page_id,
        "base_version": intent.base_version, "superseded": superseded})
    return intent


async def approve_publication_intent(db: AsyncSession, run: WorkflowRun, *, decision_id: str, card_hash: str,
                                     output_hash: str, body_hash: str) -> DocumentationWriteIntent:
    intent = await active_intent(db, run)
    if intent is None:
        raise PublicationIntentError("not_reserved", "No publication intent is reserved for this run.")
    decision = await db.get(WorkflowRunDecision, decision_id)
    if (decision is None or decision.run_id != run.id or decision.subject != PUBLICATION_SUBJECT
            or decision.action != CONFIRMED or decision.kind != "confirmation"):
        raise PublicationIntentError("approval_mismatch", "The decision is not this run's confirmed publication.")
    authority_problem = await publication_decision_problem(db, run, decision)
    if authority_problem:
        raise PublicationIntentError("approval_mismatch", authority_problem)
    if not decision.payload_hash or decision.payload_hash != card_hash:
        raise PublicationIntentError("approval_mismatch", "The card hash is not the confirmed card's hash.")
    latest = await latest_publication_decision(db, run)
    output = recorded_output(run)
    if latest is None or latest.id != decision.id or output is None or output.get("hash") != output_hash:
        raise PublicationIntentError("approval_mismatch", "The decision is not the latest confirmation of the "
                                                          "current output.")
    body_hash = "sha256:" + body_hash.removeprefix("sha256:")
    problem = confirmed_binding_problem(intent, dict(decision.payload or {}), output_hash=output_hash,
                                        body_hash=body_hash, workspace_id=run.project_id)
    if problem:
        raise PublicationIntentError("approval_mismatch", problem)
    values = {"decision_id": decision.id, "card_hash": card_hash, "output_hash": output_hash,
              "body_hash": body_hash}
    if intent.state == INTENT_RESERVED:
        await transition(db, intent, INTENT_APPROVED, approved_at=utc_now(), **values)
    elif intent.state in (INTENT_APPROVED, INTENT_NEVER_STARTED_CERTIFIED):
        if all(getattr(intent, key) == value for key, value in values.items()):
            return intent
        # Nothing was sent: a newer confirmation of the same target rebinds the approval in place.
        await transition(db, intent, str(intent.state), approved_at=utc_now(), **values)
    else:
        raise PublicationIntentError("intent_claimed", f"The publication intent is {intent.state}; it cannot be "
                                                       "approved again.")
    record_event(db, run, EVENT_APPROVED, node_id=run.current_node_id, detail={
        "intent_id": intent.id, "operation_id": intent.operation_id, "decision_id": decision.id,
        "card_hash": card_hash, "body_hash": body_hash})
    return intent


async def reserve_publication_action(db: AsyncSession, run: WorkflowRun, params: dict[str, Any] | None = None,
                                     *, transport: Any = None) -> ToolOutcome:
    from ..platform.dispatch import SUCCEEDED
    from .failure_routes import TARGET_DRIFT

    del params
    try:
        intent = await reserve_publication_intent(db, run, transport=transport)
    except PublicationIntentError as error:
        if error.code == NEEDS_CONFIGURATION:
            return s1_failure(NEEDS_CONFIGURATION, str(error), blockers=error.blockers)
        if error.code == "reconcile_first":
            from .failure_routes import PUBLISH_UNVERIFIED

            return s1_failure(PUBLISH_UNVERIFIED, str(error))
        return s1_failure(TARGET_DRIFT, str(error), blockers=error.blockers, code=error.code)
    return ToolOutcome(SUCCEEDED, {"intent_id": intent.id, "operation_id": intent.operation_id,
                                   "marker": intent.marker, "operation": intent.operation,
                                   "target": {key: getattr(intent, key) for key in _PINNED}})


__all__ = [
    "MARKER_PATTERN",
    "PUBLICATION_SUBJECT",
    "SEND_LEASE_SECONDS",
    "IntentMovedError",
    "PublicationIntentError",
    "active_intent",
    "approve_publication_intent",
    "certify_never_started",
    "claim_send",
    "latest_confirmed_intent",
    "latest_publication_decision",
    "lease_expired",
    "mark_pending_reconcile",
    "mark_sent_confirmed",
    "markers_in",
    "publication_body_hash",
    "reserve_publication_action",
    "reserve_publication_intent",
    "transition",
]
