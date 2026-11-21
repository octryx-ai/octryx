"""The one content decision record of an external coding agent's gateway request, written once at its end (I-4).

Every gateway handler (the Anthropic route and its token count, the Claude Code seat and its token count, the
``/openai`` Responses route, the Codex seat and its device admit) runs under :func:`recorded`: the request gets its
:class:`GatewayOutcome` when the handler is entered — the content deadline (``examination.RequestBudget``) starts
there and bounds the content examination, from entry to the last scan — and the handler's ``finally`` writes its
record (:meth:`GatewayOutcome.write`, idempotent: once at most), from the actual final outcome:

- refused for a content reason once its identity is bound (an unreadable, oversized or late body, a fixed rule, the
  content handling, a tool-result policy, Cedar; :meth:`GatewayOutcome.refuse`) — ``refused``, its reason, the stage
  that decided and, per kind found, the ``requested`` action and ``applied: refuse``; the refusal names the record
  (its id is fixed when the outcome starts);
- with findings to state (a kind set to ``refuse`` or ``report`` found, or a Workspace policy that would deny in
  shadow mode) and handed to the upstream or the device (:meth:`GatewayOutcome.sent`; the upstream's response
  headers arrived, :meth:`GatewayOutcome.received`, before any body read) — ``forwarded`` (sent), ``applied:
  report`` per kind, whatever the upstream answered (a non-success answer is ``upstream_status``, never a refusal:
  the body crossed the transport);
- with findings to state but not sent for another reason (a budget, the transport, a cancellation or failure;
  :meth:`GatewayOutcome.stopped`) — ``not_sent`` with that reason and stage, ``applied: none`` per kind;
- a request refused for a reason other than content (run limits, admission, a budget, authentication, a model
  denial, loop protection) with nothing found, a clean forward, or a request refused before its identity was known —
  no record (the decision log keeps decisions worth reading, ``policy_engine.decision_log``).

The first final state decides; nothing is written before the handler ends and nothing is reconciled later.
"""

from __future__ import annotations

import functools
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from fastapi import Request

from ..content_detection.examination import RequestBudget
from ..content_detection.scanner import ScanReport
from ..content_security.handling import (
    ACTION_NONE,
    ACTION_REFUSE,
    ACTION_REPORT,
    RECORD_KIND,
    SURFACE_GATEWAY,
    HandlingPlan,
)
from ..decisions.recorder import GATE_CONTENT_SECURITY, OUTCOME_DENIED, OUTCOME_REPORTED, build_gate_record
from ..model_gateway.inbound.refusals import InboundRefusal
from ..policy_engine.decision_log import record_decision
from .conversation_state import remember

STAGE_BODY = "body"
STAGE_CONTENT = "content"
STAGE_TOOL_RESULT_POLICY = "tool_result_policy"
STAGE_CEDAR = "cedar"
STAGE_BUDGET = "budget"
STAGE_UPSTREAM = "upstream"
OUTCOME_FORWARDED = "forwarded"
OUTCOME_REFUSED = "refused"
OUTCOME_NOT_SENT = "not_sent"
REASON_NOT_DISPATCHED = "not_dispatched"


@dataclass(slots=True)
class GatewayOutcome:
    """What one gateway request's record states (see the module doc)."""

    budget: RequestBudget = field(default_factory=RequestBudget)
    decision_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    route: str = ""
    alias: str = ""
    workspace_id: str = ""
    session_id: str = ""
    user_id: str = ""
    plan: HandlingPlan | None = None
    requested: dict[str, str] = field(default_factory=dict)  # the acted-on kinds found, with their action
    content: Mapping[str, Any] = field(default_factory=dict)
    policies: tuple[str, ...] = ()
    cedar: Mapping[str, Any] = field(default_factory=dict)
    fixed: str = ""
    newest: ScanReport | None = None  # the newest turn's findings (the conversation's badge)
    conversation: str = ""
    refusal: InboundRefusal | None = None
    stage: str = ""
    forwarded: bool = False
    stop: tuple[str, str] = ("", "")  # (reason, stage) of a request not sent for a reason other than content
    upstream_status: str = ""  # the reason of a non-success upstream answer to a sent request
    written: bool = False

    def bind(self, *, route: str, workspace_id: str, session_id: str, user_id: str, alias: str = "") -> None:
        """Whose request this is: from here on a refusal is recorded."""
        self.route, self.workspace_id, self.session_id, self.user_id = route, workspace_id, session_id, user_id
        self.alias = alias or self.alias

    def refuse(self, item: InboundRefusal, stage: str, *, policies: tuple[str, ...] = (),
               cedar: Mapping[str, Any] | None = None, fixed: str = "") -> InboundRefusal:
        """The request is refused for a content reason at ``stage`` (the first final state decides): ``item``
        naming the record."""
        if self.refusal is None and not self.forwarded and not self.stop[0]:
            self.refusal, self.stage, self.fixed = item, stage, fixed
            self.policies = policies or self.policies
            self.cedar = dict(cedar or self.cedar)
        return self.named(item)

    def stopped(self, item: InboundRefusal, stage: str) -> InboundRefusal:
        """The request is not sent for a reason other than content (a budget, the transport): recorded only when it
        has findings to state, and then ``item`` names the record."""
        if self.refusal is None and not self.forwarded and not self.stop[0]:
            self.stop = (item.reason, stage)
        return self.named(item)

    async def received(self, status: int) -> None:
        """The upstream's response headers arrived with ``status``: the request was sent (a non-success status is
        its ``upstream_status``), whatever reading or closing the response does next."""
        if status >= 300 and not self.upstream_status:
            self.upstream_status = f"upstream_status_{status}"
        await self.sent()

    def named(self, item: InboundRefusal) -> InboundRefusal:
        """``item`` naming the request's record, when it has one (a content refusal, or findings to state)."""
        if not self.workspace_id or (self.refusal is None and not self.stated):
            return item
        return replace(item, hint=f"{item.hint_text} Decision {self.decision_id}.")

    @property
    def reported(self) -> list[str]:
        return [kind for kind, action in self.requested.items() if action == ACTION_REPORT]

    @property
    def stated(self) -> bool:
        """Findings worth a record whatever the request's fate: an acted-on or reported kind, a shadow denial."""
        return bool(self.requested or self.cedar)

    async def sent(self) -> str:
        """The upstream took the request (or the device was handed it): the badge counts the newest turn; the
        notice the route returns names a reported kind."""
        if self.refusal is not None or self.forwarded:
            return self.notice()
        self.forwarded = True
        if self.newest is not None:
            await remember(self.session_id, self.conversation, self.newest)
        return self.notice()

    def notice(self) -> str:
        """The report notice of a sent request (empty: nothing reported)."""
        if not self.forwarded or not self.reported:
            return ""
        return f"content_handling; reported={','.join(sorted(self.reported))}; decision={self.decision_id}"

    def _outcome(self) -> str:
        if self.refusal is not None:
            return OUTCOME_REFUSED
        return OUTCOME_FORWARDED if self.forwarded else OUTCOME_NOT_SENT

    def obligation(self) -> dict[str, Any]:
        outcome = self._outcome()
        applied = {kind: ACTION_REFUSE if outcome == OUTCOME_REFUSED else action if outcome == OUTCOME_FORWARDED
                   else ACTION_NONE for kind, action in self.requested.items()}
        record: dict[str, Any] = {
            **(self.plan.record_of(applied) if self.plan is not None else {}), "kind": RECORD_KIND,
            "surface": SURFACE_GATEWAY, "requested": dict(self.requested), "applied": applied,
            "informational": [kind for kind, action in applied.items() if action == ACTION_REPORT],
            "outcome": outcome, "target": self.alias}
        if outcome == OUTCOME_REFUSED:
            record.update({"reason": self.refusal.reason, "stage": self.stage})
        elif outcome == OUTCOME_NOT_SENT:
            record.update({"reason": self.stop[0] or REASON_NOT_DISPATCHED, "stage": self.stop[1] or "dispatch"})
        record.update({key: value for key, value in (("fixed", self.fixed), ("cedar", dict(self.cedar)),
                                                     ("upstream_status", self.upstream_status)) if value})
        return record

    def write(self) -> None:
        """The request's one record (see the module doc); a second call writes nothing."""
        if self.written or not self.workspace_id:
            return
        self.written = True
        if self.refusal is None and not self.stated:
            return
        refused = self.refusal is not None
        policies = self.policies or (self.plan.policies(self.requested, ACTION_REFUSE, ACTION_REPORT)
                                     if self.plan is not None else ())
        try:
            entry = build_gate_record(
                gate=GATE_CONTENT_SECURITY, outcome=OUTCOME_DENIED if refused else OUTCOME_REPORTED,
                action="call_model", resource=f"gateway {self.route}:{self.alias}",
                principal=self.user_id or "system", workspace_id=self.workspace_id,
                session_id=self.session_id or None, rule=", ".join(policies),
                reason=self.refusal.reason if refused else None)
            entry.update({"id": self.decision_id, "determining": list(policies), "content": dict(self.content),
                          "obligation": self.obligation()})
            record_decision(entry)
        except Exception:  # noqa: BLE001 - recording never changes the decision
            return


Handler = Callable[[Request, Any], Awaitable[Any]]


def recorded(handler: Handler) -> Handler:
    """``handler`` with its request's :class:`GatewayOutcome` (started on entry, written in ``finally``)."""
    @functools.wraps(handler)
    async def run(request: Request, db: Any) -> Any:
        outcome = GatewayOutcome()
        request.state.gateway_outcome = outcome
        try:
            return await handler(request, db)
        finally:
            outcome.write()

    return run


def gateway_outcome(request: Request) -> GatewayOutcome:
    """The outcome :func:`recorded` started for ``request``."""
    return request.state.gateway_outcome


__all__ = [
    "OUTCOME_FORWARDED",
    "OUTCOME_NOT_SENT",
    "OUTCOME_REFUSED",
    "REASON_NOT_DISPATCHED",
    "STAGE_BODY",
    "STAGE_BUDGET",
    "STAGE_CEDAR",
    "STAGE_CONTENT",
    "STAGE_TOOL_RESULT_POLICY",
    "STAGE_UPSTREAM",
    "GatewayOutcome",
    "gateway_outcome",
    "recorded",
]
