"""Cedar next to the existing decision: compare, count, record — and in shadow mode never decide."""

from __future__ import annotations

import logging
import time
import uuid
from collections import Counter, OrderedDict, deque
from collections.abc import Callable, Hashable
from dataclasses import dataclass, replace

from .decision_log import record_decision
from .draft_shadow import record_draft_denial
from .engine import Evaluation, PolicySetInvalidError, compile_policy_set, evaluate
from .points import PointQuery
from .runtime import MODE_ENFORCE, MODE_OFF, PolicyRuntime, current_runtime
from .shadow_record import _entry

logger = logging.getLogger(__name__)

OUTCOME_MATCH = "match"
OUTCOME_MISMATCH = "mismatch"
OUTCOME_CUSTOM = "custom_policy"
OUTCOME_ERROR = "error"
OUTCOMES: tuple[str, ...] = (OUTCOME_MATCH, OUTCOME_MISMATCH, OUTCOME_CUSTOM, OUTCOME_ERROR)
# The refusal reason every enforcement point uses when Cedar (enforce mode) denies what it allowed.
REASON_CEDAR_POLICY_DENIED = "cedar_policy_denied"

MEMO_SIZE = 8192
LATENCY_WINDOW = 2000

_COUNTERS: Counter[tuple[str, str]] = Counter()
_LATENCIES: deque[int] = deque(maxlen=LATENCY_WINDOW)
_DRAFT_LATENCIES: deque[int] = deque(maxlen=LATENCY_WINDOW)
_MEMO: OrderedDict[Hashable, tuple[PolicyComparison, PointQuery | None]] = OrderedDict()
_FALLBACKS: Counter[str] = Counter()


@dataclass(frozen=True, slots=True)
class LegacyDecision:
    allowed: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class PolicyComparison:
    outcome: str
    cedar_allowed: bool | None
    determining: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    latency_us: int = 0
    mode: str = ""
    # The decision-log record of this comparison (non-matches only); a refusal links to it.
    record_id: str | None = None
    # Evaluated without the published custom set because it no longer parses (baseline only).
    custom_fallback: bool = False
    # Draft shadow (policy UX G8): the open draft's policies that would deny this allowed request.
    draft_blocking: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EnforcedDenial:
    policy_ids: tuple[str, ...]
    decision_id: str | None

    @property
    def message(self) -> str:
        policies = ", ".join(self.policy_ids) or "the policy engine (evaluation error)"
        reference = f" Decision {self.decision_id}." if self.decision_id else ""
        return f"Blocked by policy {policies}.{reference}"


def enforced_denial(legacy_allowed: bool, comparison: PolicyComparison | None) -> EnforcedDenial | None:
    if comparison is None or comparison.mode != MODE_ENFORCE or not legacy_allowed:
        return None
    if comparison.cedar_allowed is None or comparison.cedar_allowed:
        return None
    return EnforcedDenial(comparison.determining, comparison.record_id)


def _policies(query: PointQuery, runtime: PolicyRuntime) -> str:
    return query.policies + ("\n" + runtime.custom_text if runtime.custom_text else "")


def _evaluate(query: PointQuery, text: str) -> tuple[Evaluation, str | None]:
    try:
        compiled = compile_policy_set(text)
    except PolicySetInvalidError as error:
        return Evaluation(False, (), (error.code, *error.errors)), None
    return evaluate(compiled, query.requests, query.entities), compiled.digest


def _outcome(legacy: LegacyDecision, evaluation: Evaluation, query: PointQuery, runtime: PolicyRuntime) -> str:
    if evaluation.errors:
        return OUTCOME_ERROR
    if evaluation.allowed == legacy.allowed:
        return OUTCOME_MATCH
    custom_only = bool(evaluation.determining) and set(evaluation.determining) <= runtime.custom_ids
    if legacy.allowed and custom_only:
        baseline, _ = _evaluate(query, query.policies)
        if baseline.allowed and not baseline.errors:
            return OUTCOME_CUSTOM
    return OUTCOME_MISMATCH


def _draft_blocking(query: PointQuery, legacy: LegacyDecision, runtime: PolicyRuntime) -> tuple[str, ...]:
    if not runtime.draft_text or not legacy.allowed:
        return ()
    started = time.perf_counter()
    try:
        asked = replace(query, requests=query.draft_requests) if query.draft_requests is not None else query
        evaluation, _ = _evaluate(asked, query.policies + "\n" + runtime.draft_text)
    except Exception:  # noqa: BLE001 - the draft shadow is informational and must never touch the live shadow
        logger.warning("policy_engine_draft_shadow_failed point=%s", query.point, exc_info=True)
        return ()
    finally:
        _DRAFT_LATENCIES.append(int((time.perf_counter() - started) * 1_000_000))
    if evaluation.allowed or evaluation.errors:
        return ()
    return tuple(policy_id for policy_id in evaluation.determining if policy_id in runtime.draft_ids)


def _count_draft(query: PointQuery | None, comparison: PolicyComparison, runtime: PolicyRuntime) -> None:
    if not comparison.draft_blocking or query is None or runtime.draft_digest is None:
        return
    try:
        record_draft_denial(draft_digest=runtime.draft_digest, draft_version=runtime.draft_version or 0, query=query,
                            policy_ids=comparison.draft_blocking)
    except Exception:  # noqa: BLE001 - see _draft_blocking
        logger.warning("policy_engine_draft_shadow_record_failed", exc_info=True)


def _remember(key: Hashable, value: tuple[PolicyComparison, PointQuery | None]) -> None:
    _MEMO[key] = value
    _MEMO.move_to_end(key)
    while len(_MEMO) > MEMO_SIZE:
        _MEMO.popitem(last=False)


def shadow_decision(
    point: str, legacy: LegacyDecision, query: Callable[[], PointQuery], *, memo_key: Hashable | None = None
) -> PolicyComparison | None:
    runtime = current_runtime()
    if runtime.mode == MODE_OFF:
        return None
    memo = (runtime.key, point, memo_key, legacy.allowed) if memo_key is not None else None
    if memo is not None and memo in _MEMO:
        cached, cached_query = _MEMO[memo]
        _count(point, cached)
        _count_draft(cached_query, cached, runtime)
        return cached
    started = time.perf_counter()
    try:
        built = query()
        # A published set that no longer parses is ignored (custom policies fall back to shadow) while the baseline
        # still applies; counted per point and raised as an audited alert by the runtime (``runtime``).
        text = built.policies if runtime.custom_invalid else _policies(built, runtime)
        evaluation, digest = _evaluate(built, text)
        outcome = _outcome(legacy, evaluation, built, runtime)
        latency_us = int((time.perf_counter() - started) * 1_000_000)
        recorded = built.recorded and (outcome != OUTCOME_MATCH or (built.record_denials and not evaluation.allowed))
        record_id = str(uuid.uuid4()) if recorded else None
        comparison = PolicyComparison(outcome, evaluation.allowed, evaluation.determining, evaluation.errors,
                                      latency_us, runtime.mode, record_id, runtime.custom_invalid,
                                      _draft_blocking(built, legacy, runtime))
        if record_id is not None:
            record_decision(_entry(built, legacy, comparison, runtime, digest))
    except Exception as error:  # noqa: BLE001 - shadow evaluation must never affect the live decision
        logger.warning("policy_engine_shadow_failed point=%s", point, exc_info=True)
        _COUNTERS[(point, OUTCOME_ERROR)] += 1
        return PolicyComparison(OUTCOME_ERROR, None, (), (type(error).__name__,), mode=runtime.mode)
    _LATENCIES.append(latency_us)
    _count(point, comparison)
    _count_draft(built, comparison, runtime)
    if memo is not None:  # a repeated listing question is recorded once per snapshot, not on every turn
        _remember(memo, (comparison, built if comparison.draft_blocking else None))
    return comparison


def _count(point: str, comparison: PolicyComparison) -> None:
    _COUNTERS[(point, comparison.outcome)] += 1
    if comparison.custom_fallback:
        _FALLBACKS[point] += 1


def custom_fallback_counters() -> dict[str, int]:
    return dict(sorted(_FALLBACKS.items()))


def decision_counters() -> dict[str, dict[str, int]]:
    counters: dict[str, dict[str, int]] = {}
    for (point, outcome), count in sorted(_COUNTERS.items()):
        counters.setdefault(point, dict.fromkeys(OUTCOMES, 0))[outcome] = count
    return counters


def latency_summary(window: deque[int] | None = None) -> dict[str, float | int]:
    samples = sorted(_LATENCIES if window is None else window)
    if not samples:
        return {"samples": 0, "p50_ms": 0.0, "p95_ms": 0.0}
    return {
        "samples": len(samples),
        "p50_ms": round(samples[len(samples) // 2] / 1000, 3),
        "p95_ms": round(samples[min(len(samples) - 1, int(len(samples) * 0.95))] / 1000, 3),
    }


def draft_latency_summary() -> dict[str, float | int]:
    return latency_summary(_DRAFT_LATENCIES)


def reset_shadow_state() -> None:
    _COUNTERS.clear()
    _LATENCIES.clear()
    _DRAFT_LATENCIES.clear()
    _MEMO.clear()
    _FALLBACKS.clear()


__all__ = [
    "OUTCOMES",
    "OUTCOME_CUSTOM",
    "OUTCOME_ERROR",
    "OUTCOME_MATCH",
    "OUTCOME_MISMATCH",
    "REASON_CEDAR_POLICY_DENIED",
    "EnforcedDenial",
    "LegacyDecision",
    "PolicyComparison",
    "custom_fallback_counters",
    "enforced_denial",
    "decision_counters",
    "draft_latency_summary",
    "latency_summary",
    "reset_shadow_state",
    "shadow_decision",
]
