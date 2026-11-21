"""The Workspace's content handling (``content_security.handling``, surface ``platform``) at the tool-result check.

A tool result is the one surface where only ``refuse`` can act at once: the result is blocked
(``content_policy_denied``). ``report`` is recorded here as informational. ``mask``, ``reroute`` and
``mask_reroute`` are not applied at this surface: the result goes on unchanged, and the action applies where the
result next enters a model (the provider wrapper, ``content_security.model_call``; the gateway for an external
coding agent).

Every released tool result has at most one decision record (:class:`ToolResultHandling`), written once — when the
check returns the result to its caller (``tool_results.check_tool_result``; a check that fails or is cancelled
before that writes nothing) — from what was actually released: ``unchanged``, ``masked`` (a Workspace policy's
mask), ``blocked`` (with its ``reason``: a refused kind, a Workspace policy, an unfinished scan, a plan that cannot
be read), or ``kept_by_client`` (a coding agent's own tool whose output the launcher cannot replace: the client
keeps it unchanged, the gateway decides when it next reaches a model). Its ``obligation`` names, per kind the plan
acts on, the ``requested`` action and the action ``applied``, read from the result actually released
(:meth:`ToolResultHandling.release`: the kinds it carries): ``report`` only for a reported kind it carries, ``mask``
only for a kind found in the result and absent from the released one (a Workspace policy's mask), else ``none`` with
``applies_at: model_entrance``; a blocked result is ``refuse`` for every kind. The ``informational`` kinds are the
ones ``applied: report``. A result the client keeps is released as it came, with nothing withheld. The Workspace
policy's part (``cedar``: what it decided or, in shadow mode, would have done, and a mask's count) and the
``withheld`` count are stated only for a result released by the check (unchanged or masked); the record of an
unfinished examination is the fixed one (no finding, no plan, no policy part). A result released unchanged with
nothing to state has no record. No record claims a mask or a reroute of the content handling at the tool result.

Only a finished examination reaches this check (``tool_results`` blocks an unfinished one first), so no partial
finding selects an action here.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from ..content_security.handling import ACTION_MASK, ACTION_NONE, ACTION_REFUSE, ACTION_REPORT, HandlingPlan
from ..decisions.recorder import (
    GATE_CONTENT_SECURITY,
    OUTCOME_DENIED,
    OUTCOME_REMEDIED,
    OUTCOME_REPORTED,
    build_gate_record,
)
from ..policy_engine.decision_log import record_decision
from .decision import REASON_SCAN_UNFINISHED

POINT_TOOL_RESULT = "tool_result"
APPLIES_AT_MODEL_ENTRANCE = "model_entrance"
REASON_HANDLING_RECORDED = "content_handling_recorded"


RELEASED_UNCHANGED = "unchanged"
RELEASED_MASKED = "masked"
RELEASED_BLOCKED = "blocked"
RELEASED_KEPT_BY_CLIENT = "kept_by_client"


@dataclass(slots=True)
class ToolResultHandling:
    """One tool result's record (see the module doc): the plan's part (``refused`` policies, ``entry``), then what
    was released (:meth:`release`), written once by :meth:`write`. ``decision_id`` is fixed when it starts, so a
    notice names it before it is written."""

    refused: tuple[str, ...] = ()
    entry: dict | None = None
    decision_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    released: str = ""  # nothing released yet
    reason: str = ""
    cedar: dict[str, Any] = field(default_factory=dict)
    present: frozenset[str] = frozenset()  # the kinds the released result carries
    withheld: int = 0
    base: dict[str, Any] = field(default_factory=dict)  # gate, resource, principal, Workspace, session, counts
    written: bool = False

    def release(self, released: str, reason: str = "", *, cedar: dict[str, Any] | None = None,
                present: frozenset[str] = frozenset()) -> None:
        """What the check released (the last call decides), carrying the kinds ``present``."""
        self.released, self.reason, self.present = released, reason, present
        if cedar:
            self.cedar = dict(cedar)

    @property
    def stated(self) -> bool:
        return bool(self.released) and (self.released != RELEASED_UNCHANGED or self.entry is not None
                                        or bool(self.cedar) or bool(self.withheld)) and bool(self.base)

    def _applied(self, obligation: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
        """Per kind, the action the final release applied, and where an action not applied here applies."""
        requested: dict[str, str] = obligation["requested"]
        if self.released == RELEASED_BLOCKED:
            return {kind: ACTION_REFUSE for kind in requested}, {}
        applied = {kind: (ACTION_REPORT if action == ACTION_REPORT else ACTION_NONE) if kind in self.present
                   else ACTION_MASK if self.released == RELEASED_MASKED else ACTION_NONE
                   for kind, action in requested.items()}
        return applied, {kind: APPLIES_AT_MODEL_ENTRANCE for kind, action in applied.items() if action == ACTION_NONE}

    def write(self) -> str | None:
        """The result's one record (see the module doc); a second call writes nothing."""
        if self.written:
            return None
        self.written = True
        if not self.stated:
            return None
        released = self.released in (RELEASED_UNCHANGED, RELEASED_MASKED)  # by the check itself
        if self.reason == REASON_SCAN_UNFINISHED:  # the fixed unfinished record: no finding, plan or policy part
            self.entry, self.cedar, self.base["content"] = None, {}, {}
        obligation: dict[str, Any] = dict(self.entry["obligation"]) if self.entry else {"point": POINT_TOOL_RESULT}
        if self.entry:
            obligation["applied"], obligation["applies_at"] = self._applied(obligation)
            obligation["informational"] = [kind for kind, action in obligation["applied"].items()
                                           if action == ACTION_REPORT]
        obligation["released"] = self.released
        withheld = self.withheld if released else 0
        cedar = self.cedar if released else {}
        obligation.update({key: value for key, value in (("cedar", cedar), ("withheld", withheld),
                                                         ("reason", self.reason)) if value})
        policies = list(self.entry["determining"]) if self.entry else []
        policies += [item for item in self.cedar.get("policies", []) if item not in policies]
        outcome = OUTCOME_DENIED if self.released == RELEASED_BLOCKED else OUTCOME_REMEDIED if (
            self.released == RELEASED_MASKED or withheld) else OUTCOME_REPORTED
        try:
            entry = build_gate_record(gate=GATE_CONTENT_SECURITY, outcome=outcome, action="receive_tool_result",
                                      rule=", ".join(policies), reason=self.reason or REASON_HANDLING_RECORDED,
                                      **self.base["record"])
            entry.update({"id": self.decision_id, "determining": policies, "content": dict(self.base["content"]),
                          "obligation": obligation})
            record_decision(entry)
        except Exception:  # noqa: BLE001 - recording never changes the decision
            return None
        return self.decision_id


def _applied(requested: str, refused: bool) -> str:
    if refused:
        return ACTION_REFUSE  # the whole result is blocked
    return ACTION_REPORT if requested == ACTION_REPORT else ACTION_NONE


def tool_result_record(*, tool_name: str, workspace_id: str | None, session_id: str | None,
                       principal: str) -> ToolResultHandling:
    """The record of one tool result's check, started when the check starts (nothing acted on yet)."""
    return ToolResultHandling(base={"record": {"resource": f"tool {tool_name}", "principal": principal,
                                               "workspace_id": workspace_id, "session_id": session_id},
                                    "content": {}})


def apply_plan(handled: ToolResultHandling, plan: HandlingPlan, detected: Iterable[str],
               counts: dict[str, int]) -> ToolResultHandling:
    """The plan's disposition of a finished examination's ``detected`` kinds, into ``handled``."""
    handled.base["content"] = {"found": dict(counts)}
    found = set(detected)
    kinds = [item.kind for item in plan.items if item.kind in found and item.action != ACTION_NONE]
    if not kinds:
        return handled
    refused = plan.policies(found, ACTION_REFUSE)
    policies = refused or plan.policies(found, *{plan.action(kind) for kind in kinds})
    requested = {kind: plan.action(kind) for kind in kinds}
    applied = {kind: _applied(action, bool(refused)) for kind, action in requested.items()}
    handled.refused = refused
    handled.entry = {"determining": list(policies), "obligation": {
        **plan.record_of(kinds), "point": POINT_TOOL_RESULT, "requested": requested, "applied": applied,
        "applies_at": {kind: APPLIES_AT_MODEL_ENTRANCE for kind, action in applied.items() if action == ACTION_NONE}}}
    return handled


def handle_tool_result(plan: HandlingPlan, detected: Iterable[str], *, tool_name: str, workspace_id: str | None,
                       session_id: str | None, principal: str, counts: dict[str, int]) -> ToolResultHandling:
    """:func:`tool_result_record` with the plan applied."""
    return apply_plan(tool_result_record(tool_name=tool_name, workspace_id=workspace_id, session_id=session_id,
                                         principal=principal), plan, detected, counts)


__all__ = ["APPLIES_AT_MODEL_ENTRANCE", "POINT_TOOL_RESULT", "RELEASED_BLOCKED", "RELEASED_KEPT_BY_CLIENT",
           "RELEASED_MASKED", "RELEASED_UNCHANGED", "ToolResultHandling", "apply_plan",
           "handle_tool_result", "tool_result_record"]
