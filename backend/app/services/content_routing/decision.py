"""The content decision of one model request: scan, ask Cedar next to the built-in secret check, decide."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any

from ..content_detection.examination import DOMAIN_TEXT, Examination, RequestBudget, compose, examine
from ..content_detection.masking import PlaceholderSpans
from ..content_detection.registry import combined_definitions, detector_set_for
from ..content_detection.scanner import ENFORCEMENT_BUDGET, DetectorSet, ScanReport, Segment
from ..content_detection.vocabulary import BUILTIN_DETECTOR_IDS
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
    runtime = runtime or current_runtime()
    definitions = combined_definitions(runtime.custom_detectors, runtime.draft_detectors)
    published = BUILTIN_DETECTOR_IDS | {item.id for item in runtime.custom_detectors.detectors}
    return detector_set_for(definitions, workspace_id), frozenset(published)


# A remedy rescan without a call budget keeps the deadline every scan without one has; its filter runs under it too.
def enforcement_budget() -> RequestBudget:
    return RequestBudget(max_chars=ENFORCEMENT_BUDGET.max_chars, deadline_ms=ENFORCEMENT_BUDGET.deadline_ms)


def scan_for(segments: Sequence[Segment], workspace_id: str | None,
             runtime: PolicyRuntime | None = None, budget: RequestBudget | None = None,
             placeholders: PlaceholderSpans | None = None) -> ContentScans:
    if not segments:
        empty = compose([], domain=DOMAIN_TEXT)
        return ContentScans(empty, empty)
    detectors, published = content_detectors(workspace_id, runtime)
    examination = examine(segments, detectors, budget=budget, placeholders=placeholders)
    return ContentScans(examination.restricted(published), examination)


@lru_cache(maxsize=32)
def _named_strings(custom_text: str) -> frozenset[str]:
    return frozenset(custom_text.split('"')[1::2])


def published_policy_names(report: ScanReport, runtime: PolicyRuntime) -> bool:
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
        return self.scans.live.permits(not self.refusal)

    @property
    def cedar_denied(self) -> bool:  # an evaluation error is no answer
        comparison = self.comparison
        return comparison is not None and comparison.cedar_allowed is False and not comparison.errors

    def message(self) -> str:
        names = ", ".join(self.policies) or "the content policy"
        found = ", ".join(f"{key} ×{count}" for key, count in self.report.counts().items()) or "nothing"
        reference = f" Decision {self.decision_id}." if self.decision_id else ""
        return f"Blocked by policy {names} (found: {found}).{reference}"


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


# ``recorded`` False: a model call's caller writes the request's one record instead of the comparison.
def _with_draft(live: PointQuery, draft: PointQuery, report: ScanReport, *, recorded: bool = True) -> PointQuery:
    return replace(live, draft_requests=draft.requests, log_content=report.summary(), record_denials=True,
                   recorded=recorded)


def decide_model_content(
    *, route: str, alias: str, scans: ContentScans, builtin_check: LegacyDecision, approved_for: Iterable[str] = (),
    admission: Any = None, workspace_id: str | None = None, classification: Any = None,
    principal: Any = None, sensitive: Iterable[str] = (), builtin_secret_scan: bool = True,
) -> ContentDecision:
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
    "content_detectors",
    "published_policy_names",
    "scan_for",
]
