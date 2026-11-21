"""The content decision of one model request: scan, ask Cedar next to the built-in secret check, decide.

The gateway's built-in secret check scans the same segments: ``platform:secrets-never-leave`` is that check as a
generated policy, so the shadow comparison stays equal. The platform's own chat driver has no built-in content
check; its query leaves that policy out (a Workspace that wants it there publishes the template).

The scan runs once with the published and the draft custom detectors; the live question sees the findings of
the built-in and published detectors, the draft shadow all of them.

Outcome (:class:`ContentDecision`):

- an examination that did not finish (``content_detection.examination``) is refused
  (:data:`REASON_SCAN_UNFINISHED`) before anything else — before the Cedar query or any decision record is built, so
  neither the evaluator nor a record sink sees partial findings: neither the built-in check nor a Workspace (Cedar)
  allow can pass text that was not read — every consumer of a decision (the gateway's one decision over the forwarded
  body, governed chat first and post-remedy decisions, tool results first and post-mask decisions) gets it;
- the built-in secret check refuses → its own refusal (``secret_detected_in_prompt``), whatever Cedar says;
- engine ``enforce`` and Cedar denies → ``content_policy_denied`` naming the policies and the decision; obligations
  (mask / route) are resolved by ``obligations`` before this refusal applies on the platform's own calls (the
  gateway applies none: it refuses);
- engine ``enforce`` and Cedar cannot answer (engine unavailable, published set invalid) while the scan found
  something a published policy names → ``content_policy_unavailable``: the built-in secret check does not
  evaluate those findings, so letting it decide alone would fail open;
- otherwise the request goes on (shadow records what Cedar would have done).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any

from ..content_detection.examination import DOMAIN_TEXT, Examination, RequestBudget, compose, examine
from ..content_detection.registry import combined_definitions, detector_set_for
from ..content_detection.scanner import DetectorSet, ScanReport, Segment
from ..content_detection.vocabulary import BUILTIN_DETECTOR_IDS, DETECTOR_SECRETS
from ..policy_engine.content_points import model_content_query, tool_result_query
from ..policy_engine.points import POINT_MODEL_ADMISSION, POINT_TOOL_RESULT, PointQuery
from ..policy_engine.runtime import MODE_ENFORCE, PolicyRuntime, current_runtime
from ..policy_engine.shadow import LegacyDecision, PolicyComparison, shadow_decision

REASON_CONTENT_POLICY_DENIED = "content_policy_denied"
REASON_CONTENT_POLICY_UNAVAILABLE = "content_policy_unavailable"
REASON_SCAN_UNFINISHED = "content_scan_unfinished"


@dataclass(frozen=True, slots=True)
class ContentScans:
    live: Examination
    draft: Examination


def content_detectors(workspace_id: str | None, runtime: PolicyRuntime | None = None
                      ) -> tuple[DetectorSet, frozenset[str]]:
    """Every detector the published set and the draft define for the Workspace, and the published ids (what the
    live question sees; the draft shadow sees all)."""
    runtime = runtime or current_runtime()
    definitions = combined_definitions(runtime.custom_detectors, runtime.draft_detectors)
    published = BUILTIN_DETECTOR_IDS | {item.id for item in runtime.custom_detectors.detectors}
    return detector_set_for(definitions, workspace_id), frozenset(published)


def scan_for(segments: Sequence[Segment], workspace_id: str | None,
             runtime: PolicyRuntime | None = None, budget: RequestBudget | None = None) -> ContentScans:
    """Examine once with every detector the published set and the draft define for the Workspace; ``budget``: the
    request's one budget it is charged to (the model-call wrapper's), else the enforcement budget of this scan."""
    if not segments:
        empty = compose([], domain=DOMAIN_TEXT)
        return ContentScans(empty, empty)
    detectors, published = content_detectors(workspace_id, runtime)
    examination = examine(segments, detectors, budget=budget)
    return ContentScans(examination.restricted(published), examination)


@lru_cache(maxsize=32)
def _named_strings(custom_text: str) -> frozenset[str]:
    """Every string literal of the published custom set (detector ids and categories a policy names)."""
    return frozenset(custom_text.split('"')[1::2])


def published_policy_names(report: ScanReport, runtime: PolicyRuntime) -> bool:
    """Whether a published custom policy names a detector or category this scan found (or incompleteness)."""
    named = _named_strings(runtime.custom_text) if runtime.custom_text else frozenset()
    found = set(report.detected) | set(report.categories)
    incomplete = report.scanned and not report.complete and "content.complete" in runtime.custom_text
    return bool(found & named) or incomplete


@dataclass(frozen=True, slots=True)
class ContentDecision:
    scans: ContentScans
    comparison: PolicyComparison | None
    builtin_check: LegacyDecision
    # The reason the request is refused, or empty when it may go on (possibly changed by an obligation).
    refusal: str = ""
    policies: tuple[str, ...] = ()
    decision_id: str | None = None
    query: PointQuery | None = field(default=None, repr=False)

    @property
    def report(self) -> ScanReport:
        return self.scans.live.report

    @property
    def allowed(self) -> bool:
        """Whether the content may go on: no refusal, and the examination finished (never otherwise)."""
        return self.scans.live.permits(not self.refusal)

    def message(self) -> str:
        names = ", ".join(self.policies) or "the content policy"
        found = ", ".join(f"{key} ×{count}" for key, count in self.report.counts().items()) or "nothing"
        reference = f" Decision {self.decision_id}." if self.decision_id else ""
        return f"Blocked by policy {names} (found: {found}).{reference}"


def builtin_secret_decision(scans: ContentScans, reason: str) -> LegacyDecision:
    """The gateway's secret scan as the built-in check (the ``secrets`` detector over the same segments); an
    unfinished examination is refused before this check is read (:func:`_decide`)."""
    if DETECTOR_SECRETS in scans.live.detected:
        return LegacyDecision(False, reason)
    return LegacyDecision(True, "")


def _enforced(decision: ContentDecision, runtime: PolicyRuntime) -> ContentDecision:
    comparison = decision.comparison
    if not decision.builtin_check.allowed or runtime.mode != MODE_ENFORCE:
        return decision
    unanswered = comparison is None or comparison.cedar_allowed is None or runtime.custom_invalid
    if unanswered:
        if published_policy_names(decision.report, runtime):
            return _with(decision, REASON_CONTENT_POLICY_UNAVAILABLE)
        return decision
    if comparison.cedar_allowed:
        return decision
    return _with(decision, REASON_CONTENT_POLICY_DENIED, comparison.determining, comparison.record_id)


def _with(decision: ContentDecision, refusal: str, policies: Iterable[str] = (), decision_id: str | None = None):
    return replace(decision, refusal=refusal, policies=tuple(policies), decision_id=decision_id)


def _decide(point: str, builtin_check: LegacyDecision, scans: ContentScans, build) -> ContentDecision:
    if not scans.live.finished or not scans.draft.finished:
        # Completion first, unconditionally: no built-in or Workspace allow passes unread text, and no policy query,
        # decision record or notice is built from partial findings — they are stripped here, at the fixed boundary
        # (the decision keeps only the completion).
        stripped = ContentScans(scans.live.restricted(frozenset()), scans.draft.restricted(frozenset()))
        return ContentDecision(stripped, None, builtin_check, refusal=REASON_SCAN_UNFINISHED)
    runtime = current_runtime()
    built: dict[str, PointQuery] = {}

    def query() -> PointQuery:
        built["query"] = build(scans)
        return built["query"]

    comparison = shadow_decision(point, builtin_check, query)
    decision = ContentDecision(scans, comparison, builtin_check, query=built.get("query"))
    if not builtin_check.allowed:
        return _with(decision, builtin_check.reason, (), comparison.record_id if comparison else None)
    return _enforced(decision, runtime)


def _with_draft(live: PointQuery, draft: PointQuery, report: ScanReport, *, recorded: bool = True) -> PointQuery:
    """``recorded``: whether the comparison writes its own record (a model call's caller writes the one record of
    the request instead, I-4)."""
    return replace(live, draft_requests=draft.requests, log_content=report.summary(), record_denials=True,
                   recorded=recorded)


def decide_model_content(
    *, route: str, alias: str, scans: ContentScans, builtin_check: LegacyDecision, approved_for: Iterable[str] = (),
    admission: Any = None, workspace_id: str | None = None, classification: Any = None,
    principal: Any = None, sensitive: Iterable[str] = (), builtin_secret_scan: bool = True,
) -> ContentDecision:
    """``builtin_secret_scan``: the route has the gateway's secret scan (so ``platform:secrets-never-leave``)."""
    approved = tuple(approved_for)
    categories = tuple(sensitive)

    def build(found: ContentScans) -> PointQuery:
        def one(report: ScanReport) -> PointQuery:
            return model_content_query(route=route, alias=alias, content=report.to_cedar(), approved_for=approved,
                                       admission=admission, workspace_id=workspace_id,
                                       classification=classification, principal=principal, sensitive=categories,
                                       secret_policy=builtin_secret_scan)
        return _with_draft(one(found.live.report), one(found.draft.report), found.live.report, recorded=False)

    return _decide(POINT_MODEL_ADMISSION, builtin_check, scans, build)


def decide_tool_result(
    *, tool_name: str, family: str | None, origin: str, scans: ContentScans, workspace_id: str | None,
    classification: Any = None, connections: Iterable[str] = (), principal: Any = None,
    sensitive: Iterable[str] = (),
) -> ContentDecision:
    """``receive_tool_result``: the built-in check allows tool results; Workspace content policy supplies any
    restrictions."""
    names = tuple(connections)
    categories = tuple(sensitive)

    def build(found: ContentScans) -> PointQuery:
        def one(report: ScanReport) -> PointQuery:
            return tool_result_query(tool_name=tool_name, family=family, origin=origin, content=report.to_cedar(),
                                     workspace_id=workspace_id, classification=classification, connections=names,
                                     principal=principal, sensitive=categories)
        return _with_draft(one(found.live.report), one(found.draft.report), found.live.report, recorded=False)

    return _decide(POINT_TOOL_RESULT, LegacyDecision(True), scans, build)


__all__ = [
    "REASON_CONTENT_POLICY_DENIED",
    "REASON_CONTENT_POLICY_UNAVAILABLE",
    "REASON_SCAN_UNFINISHED",
    "ContentDecision",
    "ContentScans",
    "decide_model_content",
    "decide_tool_result",
    "builtin_secret_decision",
    "content_detectors",
    "published_policy_names",
    "scan_for",
]
