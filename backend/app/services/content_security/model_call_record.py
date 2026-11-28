"""The one record of a platform model call's content handling: request-side only."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .handling import (
    ACTION_MASK,
    ACTION_MASK_REROUTE,
    ACTION_NONE,
    ACTION_REFUSE,
    ACTION_REPORT,
    ACTION_REROUTE,
    KIND_IDS,
    MASKING,
    REASON_ROUTE_UNAVAILABLE,
    REROUTING,
    HandlingPlan,
)
from .record_types import AppliedEntry, ModelCallObligation

SURFACE_MESSAGES = "messages"
SURFACE_MESSAGE_EXTRAS = "message_extras"
SURFACE_REPLAY_ARGUMENTS = "replay_arguments"
SURFACE_OFFERED_TOOLS = "offered_tools"
SURFACE_REQUEST = "request"

OUTCOME_FORWARDED = "forwarded"
OUTCOME_REFUSED = "refused"
STAGE_INPUT = "input"
STAGE_REROUTE = "reroute"
STAGE_CEDAR = "cedar"
STAGE_FINAL_BYTES = "final_bytes"
REASON_REFUSED_KIND_MASKED = "refused_kind_masked"  # a refused kind left in older history: masked, never sent

#: Which applied action a kind's record names when its surfaces differ (the strongest first).
_STRENGTH = (ACTION_REFUSE, ACTION_MASK_REROUTE, ACTION_MASK, ACTION_REROUTE, ACTION_REPORT, ACTION_NONE)


@dataclass(frozen=True, slots=True)
class Applied:
    surface: str
    kind: str
    requested: str
    applied: str
    reason: str = ""

    def as_dict(self) -> AppliedEntry:
        item: AppliedEntry = {"surface": self.surface, "kind": self.kind, "requested": self.requested,
                              "applied": self.applied}
        if self.reason:
            item["reason"] = self.reason
        return item


def _acting(plan: HandlingPlan, kinds: Iterable[str]) -> list[str]:
    found = set(kinds)
    return [item.kind for item in plan.items if item.kind in found and item.kind in KIND_IDS
            and item.action != ACTION_NONE]


def _masked_as(action: str) -> str:
    return action if action in MASKING else ACTION_MASK


def sent_applied(plan: HandlingPlan, found: Mapping[str, Iterable[str]], present: Iterable[str]) -> list[Applied]:
    sent = frozenset(present)
    entries = [Applied(surface, kind, plan.action(kind), _masked_as(plan.action(kind)),
                       REASON_REFUSED_KIND_MASKED if plan.action(kind) == ACTION_REFUSE else "")
               for surface, kinds in found.items() for kind in _acting(plan, kinds) if kind not in sent]
    for kind in _acting(plan, sent):  # only report and reroute kinds pass the final check
        action = plan.action(kind)
        applied = ACTION_REROUTE if action in REROUTING else action
        surfaces = [surface for surface, kinds in found.items() if kind in kinds] or [SURFACE_REQUEST]
        entries += [Applied(surface, kind, action, applied) for surface in surfaces]
    return entries


def refused(plan: HandlingPlan, surface: str, kinds: Iterable[str]) -> list[Applied]:
    return [Applied(surface, kind, ACTION_REFUSE, ACTION_REFUSE) for kind in _acting(plan, kinds)
            if plan.action(kind) == ACTION_REFUSE]


def route_unavailable(plan: HandlingPlan, found: Mapping[str, Iterable[str]]) -> list[Applied]:
    return [Applied(surface, kind, plan.action(kind), ACTION_REFUSE, REASON_ROUTE_UNAVAILABLE)
            for surface, kinds in found.items() for kind in _acting(plan, kinds) if plan.action(kind) in REROUTING]


def acting_policies(plan: HandlingPlan, entries: Iterable[Applied]) -> tuple[str, ...]:
    kinds = {item.kind for item in entries if item.applied in (*MASKING, ACTION_REROUTE)}
    return plan.policies(kinds, ACTION_REFUSE, ACTION_MASK, ACTION_MASK_REROUTE, ACTION_REROUTE)


def informational_policies(plan: HandlingPlan, entries: Iterable[Applied]) -> tuple[str, ...]:
    acted = {item.kind for item in entries if item.applied != ACTION_REPORT}
    return plan.policies({item.kind for item in entries if item.kind not in acted}, ACTION_REPORT)


def call_record(plan: HandlingPlan, entries: Iterable[Applied], *, point: str, outcome: str, reason: str = "",
                stage: str = "", withheld: Mapping[str, int] | None = None,
                target: Mapping[str, object] | None = None,
                reported_before: Mapping[str, str] | None = None, reply_refused: bool = False) -> ModelCallObligation:
    items = list(dict.fromkeys(entries))
    kinds = list(dict.fromkeys(item.kind for item in items))
    applied: dict[str, str] = {}
    for item in sorted(items, key=lambda entry: _STRENGTH.index(entry.applied)):
        applied.setdefault(item.kind, item.applied)
    if reported_before:  # reported by the earlier record, sent again by this call
        for kind in reported_before:
            if kind not in applied:
                kinds.append(kind)
                applied[kind] = ACTION_REPORT
    record: ModelCallObligation = {
        **plan.record_of(kinds), "point": point, "requested": {kind: plan.action(kind) for kind in kinds},
        "applied": applied, "informational": [kind for kind, action in applied.items() if action == ACTION_REPORT],
        "surfaces": [item.as_dict() for item in items], "outcome": outcome}
    record.update({key: value for key, value in (("reason", reason), ("stage", stage)) if value})
    if withheld:
        record["withheld"] = dict(withheld)
    if target:
        record["target"] = dict(target)
    if reported_before:
        record["reported_before"] = dict(reported_before)  # kind → the earlier record that reported it
    if reply_refused:
        record["reply_refused"] = True
    return record


__all__ = [
    "OUTCOME_FORWARDED",
    "OUTCOME_REFUSED",
    "REASON_REFUSED_KIND_MASKED",
    "STAGE_CEDAR",
    "STAGE_FINAL_BYTES",
    "STAGE_INPUT",
    "STAGE_REROUTE",
    "SURFACE_MESSAGES",
    "SURFACE_MESSAGE_EXTRAS",
    "SURFACE_OFFERED_TOOLS",
    "SURFACE_REPLAY_ARGUMENTS",
    "SURFACE_REQUEST",
    "Applied",
    "acting_policies",
    "call_record",
    "informational_policies",
    "refused",
    "route_unavailable",
    "sent_applied",
]
