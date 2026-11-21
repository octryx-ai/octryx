"""Pre-dispatch compaction planning helpers for runtime prompt pressure."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ....services.model_family_policy import (
    is_fast_reasoning_model,
    is_premium_reasoning_model,
    is_weak_coding_model_family,
)
from ...core.types import ChatMessage
from ..messages._engine_message_helpers import _estimate_message_tokens, _trim_messages_to_budget

RuntimeMessageEstimator = Callable[[list[ChatMessage]], int]
RuntimeMessageTrimmer = Callable[[list[ChatMessage], int], list[ChatMessage]]

_MIN_COMPLETION_TOKENS = 256


@dataclass(frozen=True)
class _PreDispatchCompactionProfile:
    name: str
    trigger_multiplier: float
    min_prompt_tokens: int
    headroom_ratio: float
    min_target_tokens: int


@dataclass(frozen=True)
class PreDispatchCompactionPlan:
    should_compact: bool
    estimated_prompt_tokens: int
    compacted_prompt_tokens: int
    resolved_completion_tokens: int
    trigger_token_budget: int
    target_token_budget: int
    pressure_ratio: float
    model_profile: str
    reason: str
    compacted_messages: list[ChatMessage]


_PREMIUM_PROFILE = _PreDispatchCompactionProfile(
    name="premium_reasoning",
    trigger_multiplier=4.0,
    min_prompt_tokens=8_192,
    headroom_ratio=0.84,
    min_target_tokens=3_072,
)
_FAST_PROFILE = _PreDispatchCompactionProfile(
    name="fast_reasoning",
    trigger_multiplier=2.5,
    min_prompt_tokens=4_608,
    headroom_ratio=0.72,
    min_target_tokens=1_536,
)
_STANDARD_PROFILE = _PreDispatchCompactionProfile(
    name="standard_reasoning",
    trigger_multiplier=3.0,
    min_prompt_tokens=6_144,
    headroom_ratio=0.78,
    min_target_tokens=2_048,
)
_FULL_TOPOLOGY_DIAGRAM_PROFILE = _PreDispatchCompactionProfile(
    name="full_topology_diagram",
    trigger_multiplier=12.0,
    min_prompt_tokens=50_000,
    headroom_ratio=0.9,
    min_target_tokens=32_000,
)


def _requires_full_topology_diagram_context(messages: list[ChatMessage]) -> bool:
    inspected = "\n".join(
        str(message.get("content") or "")
        for message in messages[-12:]
        if message.get("role") in {"system", "tool"}
    ).lower()
    return (
        "full-overview topology diagram" in inspected
        and "aws_topology_snapshot" in inspected
        and "diagram_brief" in inspected
    )


def _compaction_profile_for_model(model_id: str) -> _PreDispatchCompactionProfile:
    normalized_model = str(model_id or "").strip().lower()
    if is_weak_coding_model_family(normalized_model) or is_fast_reasoning_model(normalized_model):
        return _FAST_PROFILE
    if is_premium_reasoning_model(normalized_model):
        return _PREMIUM_PROFILE
    return _STANDARD_PROFILE


def _apply_reasoning_effort_adjustment(
    profile: _PreDispatchCompactionProfile,
    *,
    reasoning_effort: str | None,
) -> _PreDispatchCompactionProfile:
    normalized_effort = str(reasoning_effort or "").strip().lower()
    if normalized_effort not in {"medium", "high"}:
        return profile
    trigger_multiplier = max(1.5, profile.trigger_multiplier - (0.25 if normalized_effort == "medium" else 0.5))
    headroom_ratio = max(0.6, profile.headroom_ratio - (0.04 if normalized_effort == "medium" else 0.08))
    min_prompt_tokens = int(profile.min_prompt_tokens * (0.92 if normalized_effort == "medium" else 0.84))
    return _PreDispatchCompactionProfile(
        name=f"{profile.name}_{normalized_effort}",
        trigger_multiplier=trigger_multiplier,
        min_prompt_tokens=max(profile.min_target_tokens + _MIN_COMPLETION_TOKENS, min_prompt_tokens),
        headroom_ratio=headroom_ratio,
        min_target_tokens=profile.min_target_tokens,
    )


def _resolve_completion_tokens(runtime: dict[str, Any], *, max_tokens: int) -> int:
    try:
        resolved = int(runtime.get("max_tokens_per_request") or max_tokens or 0)
    except (TypeError, ValueError):
        resolved = max_tokens or 0
    return max(_MIN_COMPLETION_TOKENS, resolved)


def _build_pre_dispatch_compaction_plan(
    *,
    messages: list[ChatMessage],
    runtime: dict[str, Any],
    max_tokens: int,
    reasoning_effort: str | None = None,
    estimate_message_tokens: RuntimeMessageEstimator = _estimate_message_tokens,
    trim_messages_to_budget: RuntimeMessageTrimmer = _trim_messages_to_budget,
) -> PreDispatchCompactionPlan:
    estimated_prompt_tokens = max(1, estimate_message_tokens(messages))
    resolved_completion_tokens = _resolve_completion_tokens(runtime, max_tokens=max_tokens)
    model_id = str(runtime.get("model") or runtime.get("model_id") or "").strip()
    profile = _apply_reasoning_effort_adjustment(
        _compaction_profile_for_model(model_id),
        reasoning_effort=reasoning_effort,
    )
    if _requires_full_topology_diagram_context(messages):
        profile = _FULL_TOPOLOGY_DIAGRAM_PROFILE
    trigger_token_budget = max(
        profile.min_prompt_tokens,
        int(resolved_completion_tokens * profile.trigger_multiplier),
    )

    if estimated_prompt_tokens <= trigger_token_budget:
        return PreDispatchCompactionPlan(
            should_compact=False,
            estimated_prompt_tokens=estimated_prompt_tokens,
            compacted_prompt_tokens=estimated_prompt_tokens,
            resolved_completion_tokens=resolved_completion_tokens,
            trigger_token_budget=trigger_token_budget,
            target_token_budget=trigger_token_budget,
            pressure_ratio=round(estimated_prompt_tokens / trigger_token_budget, 3),
            model_profile=profile.name,
            reason="within_pre_dispatch_budget",
            compacted_messages=messages,
        )

    target_token_budget = max(
        profile.min_target_tokens,
        min(
            trigger_token_budget - _MIN_COMPLETION_TOKENS,
            int(trigger_token_budget * profile.headroom_ratio),
        ),
    )
    compacted_messages = trim_messages_to_budget(messages, target_token_budget)
    compacted_prompt_tokens = max(1, estimate_message_tokens(compacted_messages))
    should_compact = compacted_messages != messages and compacted_prompt_tokens < estimated_prompt_tokens
    reason = (
        "pre_dispatch_compaction_recommended" if should_compact else "pre_dispatch_budget_exceeded_but_not_reducible"
    )

    return PreDispatchCompactionPlan(
        should_compact=should_compact,
        estimated_prompt_tokens=estimated_prompt_tokens,
        compacted_prompt_tokens=compacted_prompt_tokens,
        resolved_completion_tokens=resolved_completion_tokens,
        trigger_token_budget=trigger_token_budget,
        target_token_budget=target_token_budget,
        pressure_ratio=round(estimated_prompt_tokens / trigger_token_budget, 3),
        model_profile=profile.name,
        reason=reason,
        compacted_messages=compacted_messages,
    )
