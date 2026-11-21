"""The one record of a platform model call's content handling (``model_call``): request-side only.

A call's ``obligation`` names, per kind, the ``requested`` action (the plan's) and the action ``applied``, every
surface it was applied on (``surfaces``: ``surface``, ``kind``, ``requested``, ``applied``, and a ``reason`` where
the call was refused, ``refused_kind_masked`` for a refused kind masked in older history), the ``outcome``
(``forwarded``: handed to the transport; ``refused``: nothing was sent) with its ``reason`` and the ``stage`` that
refused it, what was ``withheld`` per surface, and the dispatch ``target`` (``requested``: the alias the call asked
for, ``handling``: the Workspace's governance alias a rerouting kind sent it to, ``final``: where it was sent — a
Cedar obligation may choose another, which the route check then refuses — or ``admitted: false`` when the target
could not be admitted). The surfaces of a call:

- ``messages`` — every message text of the provider copy and every sibling field of its blocks;
- ``message_extras`` — a message's other fields (``name``, any field a caller added);
- ``replay_arguments`` — every replayed tool call (its envelope, name and arguments);
- ``offered_tools`` — the offered tool definitions (names, descriptions, parameter schemas);
- ``request`` — the final request object the driver hands to its transport (the final check's reading of it).

The record is written once, after the request was handed to the transport (``model_call_outcome``), from the final
check's examination of the sent bytes (``content_detection.final_check``): a kind present in them ``applied`` as
configured (``report``, or ``reroute``: the call went to the governance alias — every other action keeps a kind out
of the sent bytes), a kind the completed examination of the input found and the sent bytes do not carry ``applied:
mask`` (``mask_reroute`` for such a kind); each on every input surface it was found on (a kind first seen in the
sent bytes on ``request``); a report an earlier record already stated for the same text is named in
``reported_before`` (no surface entry; only the earlier record counts it). A refused call sent nothing: every kind
it names is ``applied: refuse``. A call that was neither refused nor sent has no record. The reply writes no
per-kind evidence: a refused reply only sets ``reply_refused: true`` on the call's record.
"""

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
    """One kind's handling on one surface."""

    surface: str
    kind: str
    requested: str
    applied: str
    reason: str = ""

    def as_dict(self) -> dict[str, str]:
        item = {"surface": self.surface, "kind": self.kind, "requested": self.requested, "applied": self.applied}
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
    """What a request handed to the transport applied (see the module doc): the kinds ``present`` in its sent bytes
    as configured, a kind the completed input examination ``found`` (per surface) that they do not carry masked."""
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
    """The ``refuse`` kinds that refused the call on ``surface``."""
    return [Applied(surface, kind, ACTION_REFUSE, ACTION_REFUSE) for kind in _acting(plan, kinds)
            if plan.action(kind) == ACTION_REFUSE]


def route_unavailable(plan: HandlingPlan, found: Mapping[str, Iterable[str]]) -> list[Applied]:
    """The rerouting kinds per surface of a call that cannot be rerouted: requested, and refused instead."""
    return [Applied(surface, kind, plan.action(kind), ACTION_REFUSE, REASON_ROUTE_UNAVAILABLE)
            for surface, kinds in found.items() for kind in _acting(plan, kinds) if plan.action(kind) in REROUTING]


def acting_policies(plan: HandlingPlan, entries: Iterable[Applied]) -> tuple[str, ...]:
    """The policy ids of the kinds the call masked or rerouted."""
    kinds = {item.kind for item in entries if item.applied in (*MASKING, ACTION_REROUTE)}
    return plan.policies(kinds, ACTION_REFUSE, ACTION_MASK, ACTION_MASK_REROUTE, ACTION_REROUTE)


def informational_policies(plan: HandlingPlan, entries: Iterable[Applied]) -> tuple[str, ...]:
    """The policy ids of the kinds the call only reported."""
    acted = {item.kind for item in entries if item.applied != ACTION_REPORT}
    return plan.policies({item.kind for item in entries if item.kind not in acted}, ACTION_REPORT)


def call_record(plan: HandlingPlan, entries: Iterable[Applied], *, point: str, outcome: str, reason: str = "",
                stage: str = "", withheld: Mapping[str, int] | None = None,
                target: Mapping[str, object] | None = None,
                reported_before: Mapping[str, str] | None = None, reply_refused: bool = False) -> dict[str, object]:
    """The call's ``obligation`` (see the module doc)."""
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
    record: dict[str, object] = {
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
