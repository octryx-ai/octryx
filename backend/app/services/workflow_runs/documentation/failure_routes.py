"""The publish & prove publication failure routes.

These classes belong to the publish & prove path only. The global failure classes and ``CLASS_SAFETY`` are not
changed: ``action_failures.RECOVERABLE`` does not list these classes, and the graph wires each
route below explicitly (pause reason, waiting kind, resume). A provider answer that matches an existing class
(``permission`` for 401/403, ``external`` for another definite 4xx refusal) keeps that existing class and its
existing ``action_failed`` pause.

Each route says whether it is resumable, which node it resumes at, the pause reason / waiting kind, the UI
actions the requester sees, the resume event and the attempt budget.

- ``publish_unverified``: a request may have reached Confluence and reconciliation could not adopt this exact
  approved attempt (zero matches, a changed or duplicated candidate, an unproven read-back). Retry reconciles
  first, never a second write.
- ``reconcile_incomplete``: the parent scan or a candidate read was incomplete (pagination error, scan cap,
  unreadable or malformed candidate). Never absence; retry scans again.
- ``page_changed``: HTTP 409 at the transport or a base-version drift seen before the send, or the page moved on
  after this write. A new card (b) on the new base (reserve again), never a refetch-and-overwrite.
- ``target_drift``: the pinned connection, instance, space, parent or Workspace settings changed, or the parent /
  page disappeared. A new card (b) (reserve again).
- ``provider_unavailable``: Confluence did not answer before anything was sent (or a read-back failed after a
  confirmed send). Retry the action.
- ``publication_stopped``: the run was stopped or card (b) was not the latest decision at dispatch. Not resumable.
- ``needs_configuration``: no documentation space/parent, no usable connection, or an instance outside the
  Cloud v2 profile. Fix the configuration, then retry.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..platform.dispatch import CLASS_EXTERNAL, CLASS_PERMISSION, FAILED, ToolOutcome
from .confluence_v2_errors import (
    KIND_CONFLICT,
    KIND_MALFORMED,
    KIND_NOT_FOUND,
    KIND_PERMISSION,
    KIND_REJECTED,
    KIND_TRANSPORT,
    KIND_UNAVAILABLE,
    V2Error,
)

PUBLISH_UNVERIFIED = "publish_unverified"
RECONCILE_INCOMPLETE = "reconcile_incomplete"
PAGE_CHANGED = "page_changed"
TARGET_DRIFT = "target_drift"
PROVIDER_UNAVAILABLE = "provider_unavailable"
PUBLICATION_STOPPED = "publication_stopped"
NEEDS_CONFIGURATION = "needs_configuration"

S1_CLASSES: tuple[str, ...] = (PUBLISH_UNVERIFIED, RECONCILE_INCOMPLETE, PAGE_CHANGED, TARGET_DRIFT,
                               PROVIDER_UNAVAILABLE, PUBLICATION_STOPPED, NEEDS_CONFIGURATION)

# Node ids of the publish & prove graph (the contract names).
NODE_RESERVE = "reserve_publication"
NODE_CONFIRM = "confirm_publication"
NODE_PUBLISH = "publish_docs"

NEXT_PAUSE = "pause"
NEXT_RECONFIRM = "reconfirm"  # the existing ``reconfirm`` route of the publish action
NEXT_STOPPED = "stopped"
ROUTE_RECONFIRM = "reconfirm"


@dataclass(frozen=True, slots=True)
class S1Route:
    failure_class: str
    resumable: bool
    next: str
    node: str
    pause_reason: str | None
    ui_actions: tuple[str, ...]
    resume_event: str | None
    attempt_budget: int | None
    text: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ui_actions"] = list(self.ui_actions)
        return data


S1_ROUTES: dict[str, S1Route] = {route.failure_class: route for route in (
    S1Route(PUBLISH_UNVERIFIED, True, NEXT_PAUSE, NODE_PUBLISH, "publish_unverified",
            ("retry_reconcile", "change", "abort"), "retry_action", 3,
            "the publication may have reached Confluence and could not be proven as the approved attempt"),
    S1Route(RECONCILE_INCOMPLETE, True, NEXT_PAUSE, NODE_PUBLISH, "reconcile_incomplete",
            ("retry_reconcile", "change", "abort"), "retry_action", 3,
            "the check for an earlier publication could not read everything it needs"),
    S1Route(PAGE_CHANGED, True, NEXT_RECONFIRM, NODE_RESERVE, None,
            ("review_new_version",), "publication_confirmed", None,
            "the page changed in Confluence; confirm the publication on its current version"),
    S1Route(TARGET_DRIFT, True, NEXT_RECONFIRM, NODE_RESERVE, None,
            ("review_new_target",), "publication_confirmed", None,
            "the publication target changed after the confirmation; confirm it again"),
    S1Route(PROVIDER_UNAVAILABLE, True, NEXT_PAUSE, NODE_PUBLISH, "action_failed",
            ("retry_action", "change_plan", "abort"), "retry_action", 3,
            "Confluence did not answer; nothing unproven was written"),
    S1Route(PUBLICATION_STOPPED, False, NEXT_STOPPED, NODE_PUBLISH, None, (), None, None,
            "the run was stopped or the publication is no longer the confirmed decision"),
    S1Route(NEEDS_CONFIGURATION, True, NEXT_PAUSE, NODE_RESERVE, "needs_configuration",
            ("retry_action", "abort"), "retry_action", None,
            "the documentation target is not configured for Confluence Cloud publication"),
)}


def route_for(failure_class: str) -> S1Route | None:
    return S1_ROUTES.get(failure_class)


def class_of_v2_error(error: V2Error, *, before_send: bool) -> str:
    """The publish & prove (or existing) failure class of a classified provider error.

    ``before_send``: the error came from a read before any mutating request, or from a mutating request that
    certainly did not apply (``sent`` = no / refused). A possibly applied send is never classified here: it goes
    to reconciliation.
    """
    if error.kind == KIND_CONFLICT:
        return PAGE_CHANGED  # HTTP 409, by status code only
    if error.kind == KIND_PERMISSION:
        return CLASS_PERMISSION
    if error.kind == KIND_NOT_FOUND:
        return TARGET_DRIFT
    if error.kind == KIND_REJECTED:
        return CLASS_EXTERNAL
    if error.kind in (KIND_UNAVAILABLE, KIND_TRANSPORT):
        return PROVIDER_UNAVAILABLE if before_send else PUBLISH_UNVERIFIED
    if error.kind == KIND_MALFORMED:
        return TARGET_DRIFT if before_send else PUBLISH_UNVERIFIED
    return PUBLISH_UNVERIFIED


def s1_failure(failure_class: str, reason: str, **detail: Any) -> ToolOutcome:
    """A FAILED outcome carrying the publish & prove route; reconfirm classes also carry ``route: reconfirm``."""
    route = route_for(failure_class)
    result: dict[str, Any] = {"s1_failure": {"class": failure_class, **(route.to_dict() if route else {})},
                              **detail}
    if route is not None and route.next == NEXT_RECONFIRM:
        result["route"] = ROUTE_RECONFIRM
        result.setdefault("reasons", [reason])
    return ToolOutcome(FAILED, result, reason[:500], failure_class=failure_class)


__all__ = [
    "NEEDS_CONFIGURATION",
    "NODE_CONFIRM",
    "NODE_PUBLISH",
    "NODE_RESERVE",
    "PAGE_CHANGED",
    "PROVIDER_UNAVAILABLE",
    "PUBLICATION_STOPPED",
    "PUBLISH_UNVERIFIED",
    "RECONCILE_INCOMPLETE",
    "S1_CLASSES",
    "S1_ROUTES",
    "TARGET_DRIFT",
    "S1Route",
    "class_of_v2_error",
    "route_for",
    "s1_failure",
]
