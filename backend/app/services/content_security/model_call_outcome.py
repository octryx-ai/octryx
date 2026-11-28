"""The outcome of one platform model call's content handling: its one record and its notice."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..content_detection.examination import DOMAIN_TEXT, Examination, compose
from ..content_routing.notices import ATTEMPT_KEY, REASON_APPLIED
from ..decisions.recorder import (
    GATE_CONTENT_SECURITY,
    OUTCOME_DENIED,
    OUTCOME_REMEDIED,
    OUTCOME_REPORTED,
    build_gate_record,
)
from ..policy_engine.decision_log import record_decision
from .handling import ACTION_REPORT, MASKING, POLICY_UNSCANNED_WITHHELD, HandlingPlan
from .model_call_fields import REPORTED, RecordedRun, Reports, counted
from .model_call_record import (
    OUTCOME_FORWARDED,
    OUTCOME_REFUSED,
    Applied,
    acting_policies,
    call_record,
    informational_policies,
    sent_applied,
)
from .model_call_scope import bound_scope
from .refusal import ContentPolicyRefusedError

ACTION_CALL_MODEL = "call_model"
REASON_DENIED = "content_policy_denied"
REASON_UNREADABLE = "content_unreadable"

def write_record(outcome: str, policies: tuple[str, ...], examination: Examination, resource: str,
                 handling: Mapping[str, Any] | None = None, decision_id: str | None = None) -> str | None:
    scope = bound_scope()
    try:
        entry = build_gate_record(gate=GATE_CONTENT_SECURITY, outcome=outcome, action=ACTION_CALL_MODEL,
                                  resource=resource, principal=(scope.user_id if scope else None) or "system",
                                  workspace_id=scope.workspace_id if scope else None,
                                  session_id=scope.session_id if scope else None, rule=", ".join(policies))
        if decision_id:
            entry["id"] = decision_id
        entry["determining"] = list(policies)
        entry["content"] = examination.report.summary()
        if scope is not None and scope.platform is not None:
            entry["platform_scope"] = scope.platform.reason
        if handling:
            entry["obligation"] = dict(handling)
        record_decision(entry)
        return entry["id"]
    except Exception:  # noqa: BLE001 - recording never changes the decision
        return None


def refusal_error(policies: tuple[str, ...], examination: Examination, model: str, reason: str,
                  decision_id: str | None) -> ContentPolicyRefusedError:
    return ContentPolicyRefusedError(policies, {
        "kind": "block", "reason": reason, "found": examination.report.counts(), "masked": 0,
        "policies": list(policies), "decision_id": decision_id, "model_from": model, "model_to": "",
    })


def _empty() -> Examination:
    return compose([], domain=DOMAIN_TEXT)


@dataclass(frozen=True, slots=True)
class _Sent:
    entries: list[Applied]
    before: dict[str, str]  # a reported kind only earlier records reported → that record
    examination: Examination  # the counts: sent kinds from the sent bytes, masked kinds from the input
    acting: tuple[str, ...]
    informational: tuple[str, ...]


@dataclass(slots=True)
class CallOutcome:
    point: str
    requested: str
    plan: HandlingPlan | None = None
    decision_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    input: RecordedRun | None = None  # the completed examination of the input (before any Workspace policy)
    reports: Reports = field(default_factory=lambda: Reports({}, {}))  # the provider copy's report kinds
    withheld_at: dict[str, int] = field(default_factory=dict)
    masked: int = 0
    rerouted: str = ""  # the governance alias a rerouting kind sent the call to
    target: str = ""  # the alias the call is sent to once a Workspace (Cedar) policy decided (empty: the requested)
    model: str = ""  # the alias the request was handed over for
    cedar: Mapping[str, Any] = field(default_factory=dict)  # what a Workspace (Cedar) policy did or would do (record)
    sent: Examination | None = None  # the final check's examination of the bytes handed to the transport
    reply_refused: bool = False
    refusal: tuple | None = None  # (gate outcome, policies, examination, obligation) of a refusal before send
    written: bool = False

    @property
    def withheld(self) -> int:
        return sum(self.withheld_at.values())

    def withhold(self, withheld_at: Mapping[str, int]) -> None:
        for surface, count in withheld_at.items():
            self.withheld_at[surface] = self.withheld_at.get(surface, 0) + count

    def copied(self, run: RecordedRun, reports: Reports) -> None:
        self.masked += run.masked
        self.withhold(run.withheld_at)
        self.reports = reports

    def dispatched(self, sent: Examination) -> None:
        self.sent = sent

    def _target(self, final: str) -> dict[str, str]:
        return {"requested": self.requested, "handling": self.rerouted, "final": final}

    def refuse(self, policies: tuple[str, ...], model: str, reason: str, stage: str, *,
               examination: Examination | None = None, entries: list[Applied] | None = None,
               target: Mapping[str, object] | None = None) -> ContentPolicyRefusedError:
        examination = examination if examination is not None else _empty()
        if self.refusal is None and self.sent is None:
            handling = None if self.plan is None else call_record(
                self.plan, entries or [], point=self.point, outcome=OUTCOME_REFUSED, reason=reason, stage=stage,
                target=target or self._target(""))
            self.model, self.refusal = model, (OUTCOME_DENIED, policies, examination, handling)
        return refusal_error(policies, examination, model, reason, self.decision_id)

    def reply_refusal(self, policies: tuple[str, ...], model: str, reason: str,
                      examination: Examination | None = None) -> ContentPolicyRefusedError:
        self.reply_refused = True
        return refusal_error(policies, examination if examination is not None else _empty(), model, reason,
                             self.decision_id)

    def _sent(self) -> _Sent | None:
        if self.plan is None or self.sent is None:
            return None
        plan, present = self.plan, self.sent.detected
        before = {kind: earlier for kind, earlier in self.reports.before.items() if kind in present}
        found = self.input.detected() if self.input is not None else {}
        entries = [entry for entry in sent_applied(plan, found, present)  # a report stated before only: no entry
                   if entry.applied in MASKING or entry.kind not in before or entry.kind in self.reports.keys]
        masked = frozenset(entry.kind for entry in entries if entry.applied in MASKING)
        parts: list[Examination | tuple] = [self.sent.restricted(frozenset(
            entry.kind for entry in entries if entry.applied not in MASKING))]
        if self.input is not None:
            parts += [*counted(self.input, masked), self.input.completion]
        acting = acting_policies(plan, entries) + ((POLICY_UNSCANNED_WITHHELD,) if self.withheld else ())
        informational = informational_policies(plan, entries)
        informational += tuple(item for item in plan.policies(before, ACTION_REPORT) if item not in informational)
        return _Sent(entries, before, compose(parts, domain=DOMAIN_TEXT), acting, informational)

    def _sent_record(self, sent: _Sent) -> tuple | None:
        if self.plan is None or not (sent.entries or sent.before or self.withheld or self.cedar or self.reply_refused):
            return None
        handling = call_record(self.plan, sent.entries, point=self.point, outcome=OUTCOME_FORWARDED,
                               withheld=self.withheld_at, target=self._target(self.model),
                               reported_before=sent.before, reply_refused=self.reply_refused)
        if self.cedar:
            handling["cedar"] = dict(self.cedar)
        cedar_policies = tuple(str(item) for item in self.cedar.get("policies") or ())
        return (self._applied_outcome(sent), (*cedar_policies, *sent.acting, *sent.informational), sent.examination,
                handling)

    def _applied_outcome(self, sent: _Sent) -> str:
        masked = any(entry.applied in MASKING for entry in sent.entries)
        return OUTCOME_REMEDIED if masked or self.masked or self.withheld or self.rerouted else OUTCOME_REPORTED

    def forwarded(self, result: Any, model: str, cedar_notice: Mapping[str, Any]) -> Any:
        sent = self._sent()
        if sent is None:
            return result
        stated = self._sent_record(sent) is not None
        notice = self._notice(cedar_notice, sent, self.decision_id if stated else None, model)
        if notice and isinstance(result, dict):
            return {**result, ATTEMPT_KEY: notice}
        return result

    def write(self) -> str | None:
        if self.written:
            return None
        self.written = True
        sent = None if self.refusal is not None else self._sent()
        record = self.refusal if sent is None else self._sent_record(sent)
        if record is None:
            return None
        outcome, policies, examination, handling = record
        decision_id = write_record(outcome, policies, examination, f"model {self.model}", handling,
                                   decision_id=self.decision_id)
        if decision_id is not None and sent is not None:
            reported = {entry.kind for entry in sent.entries if entry.applied == ACTION_REPORT}
            for kind in reported:  # the evidence of this record's reports
                for key in self.reports.keys.get(kind, ()):
                    REPORTED.remember(key, decision_id)
        return decision_id

    def _notice(self, cedar: Mapping[str, Any], sent: _Sent, decision_id: str | None,
                model: str) -> dict[str, Any]:
        if not self.masked and not self.withheld and not self.rerouted:
            return {**cedar, "decision_id": decision_id} if cedar else {}
        found = dict(cedar.get("found") or {})
        for detector, count in sent.examination.report.counts().items():
            found[detector] = found.get(detector, 0) + count
        policies = [*list(cedar.get("policies") or []), *(item for item in sent.acting
                                                           if item not in (cedar.get("policies") or []))]
        notice = {**dict(cedar), "kind": cedar.get("kind") or "mask", "reason": cedar.get("reason") or REASON_APPLIED,
                  "found": found, "masked": int(cedar.get("masked") or 0) + self.masked, "policies": policies,
                  "decision_id": decision_id, "model_from": cedar.get("model_from") or model}
        if self.withheld:
            notice["withheld"] = self.withheld
        if self.rerouted:
            notice.update({"kind": cedar.get("kind") or ("mask_reroute" if self.masked else "reroute"),
                           "model_from": self.requested, "model_to": model})
        return notice


__all__ = ["ACTION_CALL_MODEL", "REASON_DENIED", "REASON_UNREADABLE", "CallOutcome", "refusal_error",
           "write_record"]
