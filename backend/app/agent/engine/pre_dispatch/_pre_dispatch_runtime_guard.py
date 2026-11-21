"""Central pre-dispatch message guard for normalization, compaction, and observability."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ...core.context.engine_limits import APPROX_CHARS_PER_TOKEN
from ..messages._engine_message_helpers import _estimate_message_tokens
from ._history_invariant_normalization import (
    PreDispatchHistoryNormalizationPlan,
    normalize_pre_dispatch_history,
)
from ._pre_dispatch_compaction import PreDispatchCompactionPlan, _build_pre_dispatch_compaction_plan
from ._research_evidence_context import ResearchEvidenceContext, retain_research_evidence
from ._token_pressure_observability import build_token_pressure_observability_payload


@dataclass(frozen=True)
class PreDispatchRuntimeGuardResult:
    messages: list[dict[str, Any]]
    normalized_messages: list[dict[str, Any]]
    normalization_plan: PreDispatchHistoryNormalizationPlan
    compaction_plan: PreDispatchCompactionPlan
    token_pressure_payload: dict[str, Any]


def _build_history_invariant_summary(
    normalization_plan: PreDispatchHistoryNormalizationPlan,
) -> dict[str, Any]:
    finding_codes: dict[str, int] = {}
    for finding in normalization_plan.findings:
        finding_codes[finding.code] = finding_codes.get(finding.code, 0) + 1
    return {
        "requires_normalization": normalization_plan.requires_normalization,
        "finding_count": len(normalization_plan.findings),
        "finding_codes": finding_codes,
        "drop_message_count": len(normalization_plan.drop_message_indexes),
        "assistant_rewrite_count": len(normalization_plan.assistant_rewrites),
        "canonical_tool_call_count": len(normalization_plan.canonical_tool_call_ids),
    }


def prepare_pre_dispatch_runtime_messages(
    *,
    messages: list[dict[str, Any]],
    runtimes: list[dict[str, Any]],
    max_tokens: int,
    reasoning_effort: str | None,
    approx_chars_per_token: int = APPROX_CHARS_PER_TOKEN,
    research_context: ResearchEvidenceContext | None = None,
) -> PreDispatchRuntimeGuardResult:
    normalized_messages, normalization_plan = normalize_pre_dispatch_history(messages)
    selected_runtime = runtimes[0] if runtimes else {}
    compaction_plan = _build_pre_dispatch_compaction_plan(
        messages=normalized_messages,
        runtime=selected_runtime,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
    )
    dispatch_messages = compaction_plan.compacted_messages if compaction_plan.should_compact else normalized_messages
    if research_context is not None:
        dispatch_messages = retain_research_evidence(normalized_messages, research_context,
                                                      target_budget=compaction_plan.target_token_budget)
        compaction_plan = replace(compaction_plan, should_compact=dispatch_messages != normalized_messages,
            compacted_messages=dispatch_messages, compacted_prompt_tokens=max(1, _estimate_message_tokens(dispatch_messages)),
            reason="current_research_evidence_retained")
    token_pressure_payload = build_token_pressure_observability_payload(
        normalized_messages,
        dispatch_messages,
        approx_chars_per_token=approx_chars_per_token,
        compaction_stats={
            "pre_dispatch_guard": True,
            "compaction_recommended": compaction_plan.should_compact,
            "trigger_token_budget": compaction_plan.trigger_token_budget,
            "target_token_budget": compaction_plan.target_token_budget,
            "pressure_ratio": compaction_plan.pressure_ratio,
            "model_profile": compaction_plan.model_profile,
            "decision_reason": compaction_plan.reason,
        },
    )
    token_pressure_payload["history_invariant"] = _build_history_invariant_summary(normalization_plan)
    return PreDispatchRuntimeGuardResult(
        messages=dispatch_messages,
        normalized_messages=normalized_messages,
        normalization_plan=normalization_plan,
        compaction_plan=compaction_plan,
        token_pressure_payload=token_pressure_payload,
    )


__all__ = ["PreDispatchRuntimeGuardResult", "prepare_pre_dispatch_runtime_messages"]
