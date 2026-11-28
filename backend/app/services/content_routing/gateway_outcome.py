"""The one content decision record of an external coding agent's gateway request, written once at its end."""

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
    ACTION_MASK,
    ACTION_NONE,
    ACTION_REFUSE,
    ACTION_REPORT,
    RECORD_KIND,
    SURFACE_GATEWAY,
    HandlingPlan,
)
from ..content_security.record_types import GatewayObligation, GatewayRecordContent
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
    budget: RequestBudget = field(default_factory=RequestBudget)
    decision_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    route: str = ""
    alias: str = ""
    workspace_id: str = ""
    session_id: str = ""
    user_id: str = ""
    plan: HandlingPlan | None = None
    requested: dict[str, str] = field(default_factory=dict)  # the acted-on kinds found, with their action
    masked: frozenset[str] = frozenset()  # the kinds masked in the sent body (a refuse kind in older turns too)
    content: GatewayRecordContent = field(default_factory=dict)
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
        self.route, self.workspace_id, self.session_id, self.user_id = route, workspace_id, session_id, user_id
        self.alias = alias or self.alias

    def refuse(self, item: InboundRefusal, stage: str, *, policies: tuple[str, ...] = (),
               cedar: Mapping[str, Any] | None = None, fixed: str = "") -> InboundRefusal:
        if self.refusal is None and not self.forwarded and not self.stop[0]:
            self.refusal, self.stage, self.fixed = item, stage, fixed
            self.policies = policies or self.policies
            self.cedar = dict(cedar or self.cedar)
        return self.named(item)

    def stopped(self, item: InboundRefusal, stage: str) -> InboundRefusal:
        if self.refusal is None and not self.forwarded and not self.stop[0]:
            self.stop = (item.reason, stage)
        return self.named(item)

    async def received(self, status: int) -> None:
        if status >= 300 and not self.upstream_status:
            self.upstream_status = f"upstream_status_{status}"
        await self.sent()

    def named(self, item: InboundRefusal) -> InboundRefusal:
        if not self.workspace_id or (self.refusal is None and not self.stated):
            return item
        return replace(item, hint=f"{item.hint_text} Decision {self.decision_id}.")

    @property
    def reported(self) -> list[str]:
        return [kind for kind, action in self.requested.items() if action == ACTION_REPORT]

    @property
    def stated(self) -> bool:
        return bool(self.requested or self.cedar)

    async def sent(self) -> str:
        if self.refusal is not None or self.forwarded:
            return self.notice()
        self.forwarded = True
        if self.newest is not None:
            await remember(self.session_id, self.conversation, self.newest)
        return self.notice()

    def notice(self) -> str:
        if not self.forwarded or not self.reported:
            return ""
        return f"content_handling; reported={','.join(sorted(self.reported))}; decision={self.decision_id}"

    def _outcome(self) -> str:
        if self.refusal is not None:
            return OUTCOME_REFUSED
        return OUTCOME_FORWARDED if self.forwarded else OUTCOME_NOT_SENT

    def obligation(self) -> GatewayObligation:
        outcome = self._outcome()
        applied = {kind: ACTION_REFUSE if outcome == OUTCOME_REFUSED else ACTION_NONE if outcome != OUTCOME_FORWARDED
                   else ACTION_MASK if kind in self.masked and action == ACTION_REFUSE else action
                   for kind, action in self.requested.items()}
        record: GatewayObligation = {
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
    @functools.wraps(handler)
    async def run(request: Request, db: Any) -> Any:
        outcome = GatewayOutcome()  # the content deadline starts on entry
        request.state.gateway_outcome = outcome
        response = None
        try:
            response = await handler(request, db)
            return response
        finally:
            outcome.write()
            if response is not None:
                from ..model_gateway.inbound.refusal_note import note_refusal

                await note_refusal(outcome.session_id, response)

    return run


def gateway_outcome(request: Request) -> GatewayOutcome:
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
