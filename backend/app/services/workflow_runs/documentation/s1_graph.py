"""Publish & prove: the graph's server steps and the seams to the write-intent and proof functions."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

PREFIX = "documentation."
TREE_UNCHANGED = "documentation.tree_unchanged"
PREFLIGHT = "documentation.preflight"
RESERVE_PUBLICATION = "documentation.reserve_publication"
PUBLISH_V2 = "documentation.publish_v2"
SYNC_PUBLISHED_VERSION = "documentation.sync_published_version"
AUDIENCE_PROOF = "documentation.audience_proof"
ACCEPTANCE_OPEN = "documentation.acceptance_open"
FOLLOWUP_CREATE = "documentation.followup_create"
FOLLOWUP_READBACK = "documentation.followup_readback"
DONE_CHECK = "documentation.done_check"

SUCCEEDED, FAILED, RECONFIRM = "succeeded", "failed", "reconfirm"
ROUTE_ACCEPTED, ROUTE_REJECTED = "accepted", "rejected"
ROUTE_BLOCKED, ROUTE_EXCEPTION = "blocked", "exception"
ROLE_AUDIENCE, ROLE_OUTSIDER = "audience", "outsider"

S1_ACTION_ROUTES: dict[str, frozenset[str]] = {
    TREE_UNCHANGED: frozenset({SUCCEEDED, FAILED}),
    PREFLIGHT: frozenset({SUCCEEDED, FAILED}),
    RESERVE_PUBLICATION: frozenset({SUCCEEDED, FAILED}),
    PUBLISH_V2: frozenset({SUCCEEDED, FAILED, RECONFIRM}),
    SYNC_PUBLISHED_VERSION: frozenset({SUCCEEDED, FAILED}),
    AUDIENCE_PROOF: frozenset({SUCCEEDED, FAILED}),
    ACCEPTANCE_OPEN: frozenset({ROUTE_ACCEPTED, ROUTE_REJECTED, FAILED}),
    FOLLOWUP_CREATE: frozenset({SUCCEEDED, FAILED}),
    FOLLOWUP_READBACK: frozenset({ROUTE_BLOCKED, ROUTE_EXCEPTION, FAILED}),
    DONE_CHECK: frozenset({SUCCEEDED, FAILED}),
}
S1_ACTION_CLASSES: dict[str, str] = {
    TREE_UNCHANGED: "read_only", PREFLIGHT: "read_only", RESERVE_PUBLICATION: "change", PUBLISH_V2: "deliver",
    SYNC_PUBLISHED_VERSION: "change", AUDIENCE_PROOF: "change", ACCEPTANCE_OPEN: "read_only",
    FOLLOWUP_CREATE: "deliver", FOLLOWUP_READBACK: "read_only", DONE_CHECK: "read_only",
}
S1_ACTION_PARAMS: dict[str, tuple[tuple[str, frozenset[str]], ...]] = {
    AUDIENCE_PROOF: (("principal_role", frozenset({ROLE_AUDIENCE, ROLE_OUTSIDER})),),
}

# Publish & prove failure classes the run routes (``action_failures``); the global ``safety`` stays non-recoverable.
CLASS_NEEDS_CONFIGURATION = "needs_configuration"
CLASS_PUBLISH_UNVERIFIED = "publish_unverified"
CLASS_PAGE_CHANGED = "page_changed"
CLASS_TARGET_DRIFT = "target_drift"
CLASS_PROVIDER_UNAVAILABLE = "provider_unavailable"
CLASS_RECONCILE_INCOMPLETE = "reconcile_incomplete"
CLASS_PARSE_FAILED = "parse_failed"
CLASS_INDEX_TIMEOUT = "index_timeout"
CLASS_AUDIENCE_UNPROVEN = "audience_unproven"
RECONFIRM_CLASSES = frozenset({CLASS_PAGE_CHANGED, CLASS_TARGET_DRIFT})

CONTEXT_KEY = "publish_prove"

INTERFACES: dict[str, str] = {
    "reserve_publication_intent": "write_intent",
    "approve_publication_intent": "write_intent",
    "publish_documentation_v2": "publication_v2",
    "reconcile_publication_intent": "publication_recovery",
    "sync_published_version": "knowledge",
    "issue_audience_challenge": "audience_receipt",
    "consume_audience_receipt": "audience_receipt",
    "validate_current_publication_proof": "audience_receipt",
}
OVERRIDES: dict[str, Callable[..., Any]] = {}


class NotIntegratedError(LookupError):
    pass


def interface(name: str) -> Callable[..., Any]:
    if name in OVERRIDES:
        return OVERRIDES[name]
    module = INTERFACES.get(name)
    if module is None:
        raise NotIntegratedError(name)
    try:
        found = getattr(importlib.import_module(f"{__package__}.{module}"), name, None)
    except ImportError as error:
        raise NotIntegratedError(name) from error
    if found is None:
        raise NotIntegratedError(name)
    return found


def _not_integrated(name: str):
    from ..platform.dispatch import CLASS_NOT_CONFIGURED, FAILED, ToolOutcome

    return ToolOutcome(FAILED, {"not_integrated": name}, f"{name} is not integrated in this build",
                       failure_class=CLASS_NOT_CONFIGURED)


async def _call(name: str, *args: Any, **kwargs: Any) -> Any:
    from ..platform.dispatch import ToolOutcome, class_of_exception

    try:
        function = interface(name)
    except NotIntegratedError:
        return _not_integrated(name)
    try:
        return await function(*args, **kwargs)
    except Exception as error:  # a refusal is a failed step with its reason, like a tool that raised
        code = str(getattr(error, "code", "") or "")
        declared = str(getattr(error, "failure_class", "") or "")
        failure = declared if declared in _NAMED_CLASSES | {"safety", "permission", "invalid"} else (
            code if code in _NAMED_CLASSES else class_of_exception(error))
        return ToolOutcome(FAILED, {"error_code": code} if code else {}, f"{name}: {error}"[:500],
                           failure_class=failure)


_NAMED_CLASSES = frozenset({CLASS_NEEDS_CONFIGURATION, CLASS_PUBLISH_UNVERIFIED, CLASS_PAGE_CHANGED,
                            CLASS_TARGET_DRIFT, CLASS_PROVIDER_UNAVAILABLE, CLASS_RECONCILE_INCOMPLETE,
                            CLASS_PARSE_FAILED, CLASS_INDEX_TIMEOUT, CLASS_AUDIENCE_UNPROVEN})


def _is_outcome(value: Any) -> bool:
    from ..platform.dispatch import ToolOutcome

    return isinstance(value, ToolOutcome)


def facts(run: Any) -> dict[str, Any]:
    return dict(dict(run.context or {}).get(CONTEXT_KEY) or {})


def set_facts(run: Any, **values: Any) -> dict[str, Any]:
    current = {**facts(run), **values}
    run.context = {**dict(run.context or {}), CONTEXT_KEY: current}
    return current


async def active_intent(db: Any, run: Any) -> Any:
    from sqlalchemy import select

    from ....models.runtime.documentation_publication import (
        DOCUMENTATION_SLOT,
        INTENT_ACTIVE_STATES,
        DocumentationWriteIntent,
    )

    return (await db.execute(select(DocumentationWriteIntent).where(
        DocumentationWriteIntent.run_id == run.id, DocumentationWriteIntent.slot == DOCUMENTATION_SLOT,
        DocumentationWriteIntent.state.in_(INTENT_ACTIVE_STATES)).limit(1))).scalar_one_or_none()


async def latest_intent(db: Any, run: Any) -> Any:
    from sqlalchemy import select

    from ....models.runtime.documentation_publication import DOCUMENTATION_SLOT, DocumentationWriteIntent

    bound = str(facts(run).get("intent_id") or "")
    if bound:
        current = await db.get(DocumentationWriteIntent, bound)
        seen: set[str] = set()
        while current is not None:
            if current.id in seen or current.run_id != run.id or current.slot != DOCUMENTATION_SLOT:
                return None
            seen.add(current.id)
            if not current.superseded_by_id:
                return current
            current = await db.get(DocumentationWriteIntent, current.superseded_by_id)
        return None
    return (await db.execute(select(DocumentationWriteIntent).where(
        DocumentationWriteIntent.run_id == run.id, DocumentationWriteIntent.slot == DOCUMENTATION_SLOT)
        .order_by(DocumentationWriteIntent.created_at.desc()).limit(1))).scalar_one_or_none()



async def _reserve(db: Any, run: Any) -> tuple[Any, str]:
    from ..platform.dispatch import ToolOutcome

    intent = await _call("reserve_publication_intent", db, run)
    if _is_outcome(intent):
        return intent, SUCCEEDED if intent.ok else FAILED
    set_facts(run, intent_id=intent.id, marker=intent.marker, operation_id=intent.operation_id)
    return ToolOutcome(SUCCEEDED, {"intent_id": intent.id, "operation_id": intent.operation_id,
                                   "marker": intent.marker}), SUCCEEDED


def _publish_route(outcome: Any) -> str:
    if outcome.ok:
        return SUCCEEDED
    if outcome.result.get("route") == RECONFIRM or outcome.failure_class in RECONFIRM_CLASSES:
        return RECONFIRM  # a new card (b) on the new base; never a refetch-and-overwrite
    return FAILED


async def _publish(db: Any, run: Any) -> tuple[Any, str]:
    from ....models.runtime.documentation_publication import INTENT_POTENTIALLY_SENT_STATES, INTENT_SENDABLE_STATES
    from ....time_utils import utc_now
    intent = await active_intent(db, run)
    # A confirmed send can survive a process crash before the graph ledger is recorded. The provider service
    # also knows completed intents and verifies them without another write; never reject its recovery here.
    outcome = None
    if intent is not None and intent.state in INTENT_POTENTIALLY_SENT_STATES:
        reconciled = await _call("reconcile_publication_intent", db, run)
        await db.refresh(intent)
        if intent.state in INTENT_SENDABLE_STATES:
            outcome = None  # executor-certified never started: the only way back to a send
        elif reconciled.ok:
            outcome = reconciled  # the approved attempt was adopted; nothing is sent again
        else:
            return reconciled, _publish_route(reconciled)  # an incomplete or empty scan never counts as absent
    if outcome is None:
        outcome = await _call("publish_documentation_v2", db, run)
    route = _publish_route(outcome)
    if route == SUCCEEDED:
        from ....models import WorkflowRunDecision
        from ..platform.dispatch import ToolOutcome

        intent = await latest_intent(db, run)
        if intent is None:
            return ToolOutcome(FAILED, reason="the confirmed publication has no bound intent",
                               failure_class="safety"), FAILED

        decision_id = str(facts(run).get("publication_decision_id") or "")
        decision = await db.get(WorkflowRunDecision, decision_id) if decision_id else None
        confirmed = dict(decision.payload or {}) if decision is not None else {}
        set_facts(run, publication={
            "intent_id": intent.id, "page_id": str(outcome.result.get("page_id") or ""),
            "version": outcome.result.get("version"), "location": outcome.result.get("location"),
            "storage_digest": outcome.result.get("storage_digest"), "published_at": utc_now().isoformat(),
            "decision_id": decision_id or None,
            # The immutable fact of this page version: what its confirmed body says about (a).
            "acceptance_as_published": "pending" if confirmed.get("acceptance_pending") else dict(
                confirmed.get("acceptance") or {}).get("state"),
            "acceptance_as_of": confirmed.get("acceptance_as_of")})
    return outcome, route


async def _sync(db: Any, run: Any) -> tuple[Any, str]:
    from ....time_utils import utc_now

    outcome = await _call("sync_published_version", db, run)
    if outcome.ok:
        published = dict(facts(run).get("publication") or {})
        digests = dict(outcome.result.get("digests") or {})
        set_facts(run, sync={
            **{key: outcome.result.get(key) for key in ("page_version", "revision_id")},
            **{key: digests.get(key, outcome.result.get(key)) for key in (
                "storage_digest", "view_raw_digest", "document_html_digest", "index_refs_digest")},
            "published_version": published.get("version"), "at": utc_now().isoformat()})
    return outcome, SUCCEEDED if outcome.ok else FAILED


def _waiting_view(receipt: Any, role: str) -> dict[str, Any]:
    return {"subject": "audience_receipt", "principal_role": role, "challenge_id": receipt.challenge_id,
            "receipt_id": receipt.id, "expected_principal_id": receipt.expected_principal_id,
            "page_id": receipt.page_id, "page_version": receipt.page_version, "source_key": receipt.source_key,
            "expected_outcome": "negative" if role == ROLE_OUTSIDER else "positive",
            "expires_at": receipt.expires_at.isoformat() if receipt.expires_at else None,
            "question": (f"Waiting for the {'outsider' if role == ROLE_OUTSIDER else 'audience'} principal to run "
                         "the audience check while signed in as themselves")}


async def _audience(db: Any, run: Any, params: dict[str, Any], node: Any) -> tuple[Any, str]:
    from ....time_utils import utc_now
    from ..platform.dispatch import ToolOutcome
    from ..platform_actions import WAIT
    from ..states import STATUS_WAITING, WAITING_AUDIENCE_RECEIPT

    role = str(params.get("principal_role") or ROLE_AUDIENCE)
    receipt = await _call("issue_audience_challenge", db, run, principal_role=role)
    if _is_outcome(receipt):
        if not receipt.ok and not receipt.failure_class:
            receipt.failure_class = CLASS_AUDIENCE_UNPROVEN
        return receipt, SUCCEEDED if receipt.ok else FAILED
    run.status, run.waiting_kind = STATUS_WAITING, WAITING_AUDIENCE_RECEIPT
    state = dict(run.node_state or {})
    run.node_state = {**state, "waiting": {"kind": WAITING_AUDIENCE_RECEIPT, "title": node.title,
                                           "since": utc_now().isoformat(), **_waiting_view(receipt, role)}}
    audience = dict(facts(run).get("audience") or {})
    audience[role] = {"receipt_id": receipt.id, "challenge_id": receipt.challenge_id, "node_id": node.id,
                      "issued_at": utc_now().isoformat(), "consumed": False}
    set_facts(run, audience=audience)
    return ToolOutcome("waiting", {"challenge_id": receipt.challenge_id, "principal_role": role}), WAIT


async def check_audience_receipt(db: Any, run: Any, *, actor_id: str | None) -> str:
    from ....time_utils import utc_now
    from ..action_failures import record_failure
    from ..engine import resolve_current_node
    from ..engine_context import _set_context
    from ..external_step import pass_key
    from ..records import record_event
    from ..states import STATUS_WAITING, WAITING_AUDIENCE_RECEIPT

    if run.status != STATUS_WAITING or run.waiting_kind != WAITING_AUDIENCE_RECEIPT:
        return "not_waiting"
    waiting = dict(dict(run.node_state or {}).get("waiting") or {})
    role = str(waiting.get("principal_role") or ROLE_AUDIENCE)
    outcome = await _call("consume_audience_receipt", db, run, principal_role=role)
    if not outcome.ok and outcome.result.get("pending"):
        return "pending"  # P has not run the check yet: the run keeps waiting (reminder / timeout policy)
    node_id = str(run.current_node_id or "")
    route = SUCCEEDED if outcome.ok else FAILED
    if not outcome.ok:
        record_failure(run, node_id=node_id, action=AUDIENCE_PROOF, reason=outcome.reason or "the audience receipt "
                       "did not prove the page", failure_class=outcome.failure_class or CLASS_AUDIENCE_UNPROVEN)
    audience = dict(facts(run).get("audience") or {})
    audience[role] = {**dict(audience.get(role) or {}), "consumed": outcome.ok, "at": utc_now().isoformat(),
                      **({"result": {key: outcome.result.get(key) for key in (
                          "receipt_id", "outcome", "page_id", "page_version", "result_digest")}} if outcome.ok
                         else {"refused": outcome.reason[:300]})}
    set_facts(run, audience=audience)
    _set_context(run, "action_ledger", pass_key(run, node_id), {"action": AUDIENCE_PROOF, "result": route})
    record_event(db, run, "audience_receipt", node_id=node_id, actor_id=actor_id,
                 detail={"principal_role": role, "result": route, "reason": outcome.reason or None})
    await resolve_current_node(db, run, route, actor_id=actor_id)
    return route


async def audience_receipt_recorded(db: Any, run_id: str) -> str:
    from ....models import WorkflowRun
    from ..records import lock_run

    run = await db.get(WorkflowRun, run_id)
    if run is None:
        return "not_waiting"
    run = await lock_run(db, run)
    return await check_audience_receipt(db, run, actor_id=None)


async def approve_publication(db: Any, run: Any, decision: Any, payload: dict[str, Any]) -> None:
    from ..records import WorkflowRunError

    try:
        approve = interface("approve_publication_intent")
    except NotIntegratedError as error:
        raise WorkflowRunError("publication_not_integrated", "The publication cannot be approved in this build.",
                               409) from error
    await db.flush()
    await approve(db, run, decision_id=decision.id, card_hash=decision.payload_hash,
                  output_hash=str(payload.get("output_hash") or ""), body_hash=str(payload.get("canonical_hash") or ""))
    set_facts(run, publication_decision_id=decision.id)


async def run_s1_action(db: Any, run: Any, key: str, params: dict[str, Any], node: Any) -> tuple[Any, str]:
    from . import acceptance, followup_exception, preflight, publish_prove_state, tree_check

    if key == TREE_UNCHANGED:
        outcome = await tree_check.tree_unchanged(db, run)
        return outcome, SUCCEEDED if outcome.ok else FAILED
    if key == PREFLIGHT:
        outcome = await preflight.preflight(db, run)
        return outcome, SUCCEEDED if outcome.ok else FAILED
    if key == RESERVE_PUBLICATION:
        return await _reserve(db, run)
    if key == PUBLISH_V2:
        return await _publish(db, run)
    if key == SYNC_PUBLISHED_VERSION:
        return await _sync(db, run)
    if key == AUDIENCE_PROOF:
        return await _audience(db, run, params, node)
    if key == ACCEPTANCE_OPEN:
        return await acceptance.acceptance_open(db, run, node)
    if key == FOLLOWUP_CREATE:
        outcome = await followup_exception.followup_create(db, run)
        return outcome, SUCCEEDED if outcome.ok else FAILED
    if key == FOLLOWUP_READBACK:
        return await followup_exception.followup_readback(db, run)
    if key == DONE_CHECK:
        outcome = await publish_prove_state.done_check(db, run)
        return outcome, SUCCEEDED if outcome.ok else FAILED
    raise KeyError(key)


def is_s1_action(key: str) -> bool:
    return key in S1_ACTION_ROUTES


__all__ = [
    "ACCEPTANCE_OPEN", "AUDIENCE_PROOF", "CONTEXT_KEY", "DONE_CHECK", "FOLLOWUP_CREATE", "FOLLOWUP_READBACK",
    "INTERFACES", "OVERRIDES", "PREFLIGHT", "PUBLISH_V2", "RESERVE_PUBLICATION", "S1_ACTION_CLASSES",
    "S1_ACTION_PARAMS", "S1_ACTION_ROUTES", "SYNC_PUBLISHED_VERSION", "TREE_UNCHANGED", "active_intent",
    "approve_publication", "audience_receipt_recorded", "check_audience_receipt", "facts", "interface", "is_s1_action",
    "latest_intent", "run_s1_action", "set_facts",
]
